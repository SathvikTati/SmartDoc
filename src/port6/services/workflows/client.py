from temporalio.client import Client

from port6.config import temporal_config


async def get_temporal_client() -> Client:
    return await Client.connect(
        temporal_config["host"],
        namespace=temporal_config["namespace"],
    )