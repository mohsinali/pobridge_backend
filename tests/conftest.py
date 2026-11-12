"""Deterministic test environment configuration."""

import os

TEST_ENVIRONMENT = {
    "APP_NAME": "POBridge API",
    "APP_ENV": "testing",
    "DEBUG": "false",
    "API_V1_PREFIX": "/api/v1",
    "FRONTEND_URL": "http://localhost:3000",
    "OPENAI_API_KEY": "",
    "OPENAI_MODEL": "",
    "MAX_UPLOAD_SIZE_MB": "10",
}

for variable, value in TEST_ENVIRONMENT.items():
    os.environ[variable] = value
