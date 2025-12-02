from pipecat_flows.manager import FlowManager
from .status_utils import status_updater  # Assuming this is your status update utility
from loguru import logger

class CustomFlowManager(FlowManager):
    async def set_node(self, node_name, node_config):
        # Call the parent class's set_node to maintain default behavior
        await super().set_node(node_name, node_config)

        logger.info(f"Node {node_name} state: {self.state}")

        # Check if the node config includes a ui_override
        if "ui_override" in node_config:
            # Send the ui_override message via status_updater
            await status_updater.update_status(
                f"Stage {node_name} active",
                {"node": node_name},
                ui_override=node_config["ui_override"]
            )
        else:
            # Optionally send a default status update without ui_override
            await status_updater.update_status(
                f"Stage {node_name} active",
                {"node": node_name}
            )