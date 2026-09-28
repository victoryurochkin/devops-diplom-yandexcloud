"""Small shared helpers for the diploma's Yandex Cloud maintenance scripts."""
import json
import os
from pathlib import Path
import time

import yandexcloud
from yandex.cloud.operation.operation_service_pb2 import GetOperationRequest
from yandex.cloud.operation.operation_service_pb2_grpc import OperationServiceStub


def client():
    path = os.environ.get("YC_SERVICE_ACCOUNT_KEY_FILE")
    if not path:
        raise RuntimeError("YC_SERVICE_ACCOUNT_KEY_FILE is not set")
    key = json.loads(Path(path).read_text())
    if not all(key.get(k) for k in ("id", "service_account_id", "private_key")):
        raise RuntimeError("Invalid service account key file")
    return yandexcloud.SDK(service_account_key=key)


def wait_operation(sdk, operation, timeout=180):
    api = sdk.client(OperationServiceStub)
    deadline = time.monotonic() + timeout
    while not operation.done:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Cloud operation timed out: " + operation.id)
        operation = api.Get(
            GetOperationRequest(operation_id=operation.id),
            timeout=min(30, remaining),
        )
        if not operation.done:
            time.sleep(1)
    if operation.HasField("error"):
        raise RuntimeError("Cloud operation failed: " + operation.error.message)


def write_json(path, document):
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent,
                                         delete=False, encoding="utf-8") as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            json.dump(document, output, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
