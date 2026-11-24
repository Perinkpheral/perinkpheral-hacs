# SPDX-License-Identifier: MIT
"""Running the integration inside a real Home Assistant, from docs/agent-test-plan.md.

`enable_custom_integrations` makes Home Assistant load this repository's
custom_components/perinkpheral like an installed one.
"""
import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
