"""
Karma Trust Protocol — Python SDK
==================================
One-stop import for integrating with the Karma runtime.

    from karma.sdk import KarmaClient

    client = KarmaClient(runtime_url="https://api.karma.xyz", api_key="karma_...")
    result = await client.run_task(contract, my_task_fn)
"""
from sdk.client import KarmaClient
from sdk.task import TaskRunner

__all__ = ["KarmaClient", "TaskRunner"]
