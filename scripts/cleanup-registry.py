#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import re
import time

import grpc
import yandexcloud
from yandex.cloud.containerregistry.v1.image_service_pb2 import (
    DeleteImageRequest, ListImagesRequest,
)
from yandex.cloud.containerregistry.v1.image_service_pb2_grpc import ImageServiceStub
from yandex.cloud.containerregistry.v1.registry_service_pb2 import GetRegistryRequest
from yandex.cloud.containerregistry.v1.registry_service_pb2_grpc import RegistryServiceStub
from yandex.cloud.operation.operation_service_pb2 import GetOperationRequest
from yandex.cloud.operation.operation_service_pb2_grpc import OperationServiceStub


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-id", required=True)
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    for value in (args.registry_id, args.folder_id):
        if not re.fullmatch(r"[a-z0-9]{20}", value):
            raise SystemExit("Некорректный ID реестра или каталога")

    key_path = os.environ.get("YC_SERVICE_ACCOUNT_KEY_FILE")
    if not key_path:
        raise SystemExit("Не задан YC_SERVICE_ACCOUNT_KEY_FILE")

    key = json.loads(Path(key_path).read_text())
    if not all(key.get(k) for k in ("id", "service_account_id", "private_key")):
        raise SystemExit("Некорректный ключ сервисного аккаунта")

    sdk = yandexcloud.SDK(service_account_key=key)
    registry = sdk.client(RegistryServiceStub).Get(
        GetRegistryRequest(registry_id=args.registry_id), timeout=30,
    )

    if (
        registry.folder_id != args.folder_id
        or registry.name != "diplom-registry"
        or registry.labels.get("project") != "devops-diplom"
        or registry.labels.get("managed_by") != "terraform"
    ):
        raise SystemExit("Реестр не соответствует проекту; работа остановлена")

    images_api = sdk.client(ImageServiceStub)
    operations_api = sdk.client(OperationServiceStub)

    def list_images():
        images = {}
        page_token = ""
        seen_tokens = set()

        while True:
            page = images_api.List(ListImagesRequest(
                registry_id=args.registry_id,
                page_size=1000,
                page_token=page_token,
            ), timeout=30)

            for image in page.images:
                if not image.name.startswith(args.registry_id + "/"):
                    raise SystemExit("API вернул образ другого реестра")
                images[image.id] = image

            page_token = page.next_page_token
            if not page_token:
                return images
            if page_token in seen_tokens:
                raise SystemExit("API повторил токен страницы")
            seen_tokens.add(page_token)

    def delete_image(image_id):
        operation = images_api.Delete(
            DeleteImageRequest(image_id=image_id), timeout=30,
        )
        deadline = time.monotonic() + 180

        while not operation.done:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SystemExit(f"Тайм-аут удаления образа {image_id}")

            operation = operations_api.Get(
                GetOperationRequest(operation_id=operation.id),
                timeout=min(30, remaining),
            )
            if not operation.done:
                time.sleep(1)

        if operation.HasField("error"):
            # Связанный образ попробуем удалить после остальных.
            if operation.error.code == 9:
                return False
            # NOT_FOUND: образ уже отсутствует.
            if operation.error.code != 5:
                raise SystemExit(
                    f"Ошибка удаления {image_id}: {operation.error.message}"
                )
        return True

    images = list_images()
    print(f"Сервисный аккаунт: {key['service_account_id']}", flush=True)
    print(f"Реестр: {registry.id}; образов: {len(images)}", flush=True)

    for image in images.values():
        print(image.id, image.digest, ",".join(image.tags), flush=True)

    if not args.delete:
        print("Режим просмотра: ничего не удалено")
        return

    initial_ids = set(images)

    while images:
        previous_ids = set(images)

        for image_id in images:
            try:
                deleted = delete_image(image_id)
            except grpc.RpcError as error:
                if error.code() == grpc.StatusCode.NOT_FOUND:
                    deleted = True
                elif error.code() == grpc.StatusCode.FAILED_PRECONDITION:
                    deleted = False
                else:
                    raise

            if deleted:
                print(f"Удалён: {image_id}", flush=True)

        images = list_images()

        if set(images) - initial_ids:
            raise SystemExit("Появились новые образы; остановите публикацию из CI")

        if images and set(images) == previous_ids:
            raise SystemExit(
                "Очистка остановлена: оставшиеся образы не удаляются"
            )

    print("Реестр пуст. Сам реестр удаляет Terraform.")


if __name__ == "__main__":
    try:
        main()
    except grpc.RpcError as error:
        raise SystemExit(f"Yandex API: {error.code().name}: {error.details()}")
