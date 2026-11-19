import pytest
from agentdojo.task_suite.load_suites import get_suite

from agent_eval.runner import load_policies
from agent_eval.schema import ExperimentConfig


@pytest.fixture(scope="session")
def policies():
    return load_policies(ExperimentConfig())


@pytest.fixture
def banking():
    suite = get_suite("v1.2.2", "banking")
    return suite, suite.load_and_inject_default_environment({})


@pytest.fixture
def workspace():
    suite = get_suite("v1.2.2", "workspace")
    return suite, suite.load_and_inject_default_environment({})
