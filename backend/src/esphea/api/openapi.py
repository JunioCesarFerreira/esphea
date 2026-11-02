"""Print the OpenAPI document (consumed by the frontend type generator)."""

import json

from esphea.api.app import create_app
from esphea.settings import Settings


def main() -> None:
    print(json.dumps(create_app(settings=Settings()).openapi(), indent=2))


if __name__ == "__main__":
    main()
