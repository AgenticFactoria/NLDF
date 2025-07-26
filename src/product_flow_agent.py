#!/usr/bin/env python3
"""
Product Flow Agent
Specialized agent that understands the complete product workflow and generates
optimal AGV commands based on the successful product flow pattern.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from agents import Agent, Runner, SQLiteSession

logger = logging.getLogger(__name__)


class ProductFlowAgent:
    """
    Specialized agent that understands product flow and generates optimal AGV commands.
    """

    def __init__(self, line_id: str):
        self.line_id = line_id
        self.agent = self._create_product_flow_agent()
        self.session = SQLiteSession(f"product_flow_agent_{line_id}_session")

        # Track ongoing operations to avoid conflicts
        self.ongoing_operations = {
            "raw_material_pickup": {},  # agv_id -> product_id
            "quality_check_delivery": {},  # agv_id -> product_id
            "agv_charging": [],  # agv_ids currently charging (list for JSON serialization)
        }

    def _create_product_flow_agent(self) -> Agent:
        """Create the specialized product flow agent."""
        instructions = f"""
You are a Product Flow Specialist for production line {self.line_id}.

CRITICAL COMMAND SEQUENCE RULE:
EVERY AGV OPERATION MUST FOLLOW THIS EXACT 4-STEP SEQUENCE:
1. MOVE to target location FIRST
2. LOAD/UNLOAD at that location
3. MOVE to next location
4. LOAD/UNLOAD at next location

NEVER send load/unload commands without MOVE commands first!
NEVER assume AGV is already at the right location!

VALID TARGET POINTS:
- P0: RawMaterial warehouse (for loading raw materials)
- P1: StationA (for unloading raw materials)
- P2: Conveyor_AB (automatic transfer point)
- P3: StationB (for unloading P3 products in second processing)
- P4: Conveyor_BC (automatic transfer point)
- P5: StationC (automatic processing)
- P6: Conveyor_CQ (for loading P3 products for second processing)
- P7: QualityCheck input (automatic transfer)
- P8: QualityCheck output (for loading finished products)
- P9: Warehouse (for unloading finished products)

MANDATORY COMMAND SEQUENCES:

START PRODUCTION (RawMaterial → StationA):
1. {{"action": "move", "target": "AGV_1", "params": {{"target_point": "P0"}}}}
2. {{"action": "load", "target": "AGV_1", "params": {{"product_id": "prod_1_XXXXX"}}}}
3. {{"action": "move", "target": "AGV_1", "params": {{"target_point": "P1"}}}}
4. {{"action": "unload", "target": "AGV_1", "params": {{}}}}

FINISH PRODUCTION (QualityCheck → Warehouse):
1. {{"action": "move", "target": "AGV_1", "params": {{"target_point": "P8"}}}}
2. {{"action": "load", "target": "AGV_1", "params": {{}}}}
3. {{"action": "move", "target": "AGV_1", "params": {{"target_point": "P9"}}}}
4. {{"action": "unload", "target": "AGV_1", "params": {{}}}}

P3 SECOND PROCESSING (Conveyor_CQ → StationB) - ONLY AGV_2:
1. {{"action": "move", "target": "AGV_2", "params": {{"target_point": "P6"}}}}
2. {{"action": "load", "target": "AGV_2", "params": {{"product_id": "prod_3_XXXXX"}}}}
3. {{"action": "move", "target": "AGV_2", "params": {{"target_point": "P3"}}}}
4. {{"action": "unload", "target": "AGV_2", "params": {{}}}}

CHARGING COMMAND (when battery < 30%):
{{"action": "charge", "target": "AGV_1", "params": {{"target_level": 80}}}}

VALID ACTIONS: move, load, unload, charge
VALID TARGETS: AGV_1, AGV_2

FACTORY WORKFLOW:
P0: RawMaterial → P1: StationA → [AUTO: P2→P3→P4→P5→P6→P7] → P8: QualityCheck → P9: Warehouse

PRODUCT TYPES:
- P1/P2: Single pass (RawMaterial→StationA→[AUTO]→QualityCheck→Warehouse)
- P3: Double pass (RawMaterial→StationA→[AUTO]→Conveyor_CQ→StationB→[AUTO]→QualityCheck→Warehouse)

P3 SPECIAL RULE: Only AGV_2 can access Conveyor_CQ upper_buffer at P6!

DECISION PRIORITIES:
1. CRITICAL: AGV battery < 20% → charge immediately
2. HIGH: Finished products in QualityCheck → deliver to warehouse
3. HIGH: P3 products in Conveyor_CQ upper_buffer → AGV_2 second processing
4. HIGH: Raw materials available → start new production
5. MEDIUM: AGV battery < 40% and idle → preventive charging

COMMAND VALIDATION RULES:
- Every sequence starts with MOVE command
- Load from RawMaterial (P0) specifies product_id
- Load from QualityCheck (P8) uses empty params
- P3 second processing uses AGV_2 only
- No duplicate AGV assignments in same sequence
- Only use valid target_point values (P0-P9)
- Charge command does not need target_point

RESPONSE FORMAT - ALWAYS JSON ARRAY:
[
  {{"command_id": "flow_timestamp_description", "action": "move", "target": "AGV_1", "params": {{"target_point": "P0"}}}},
  {{"command_id": "flow_timestamp_description", "action": "load", "target": "AGV_1", "params": {{"product_id": "prod_1_abc123"}}}},
  {{"command_id": "flow_timestamp_description", "action": "move", "target": "AGV_1", "params": {{"target_point": "P1"}}}},
  {{"command_id": "flow_timestamp_description", "action": "unload", "target": "AGV_1", "params": {{}}}}
]

REMEMBER: MOVE FIRST, THEN LOAD/UNLOAD!
"""

        return Agent(
            name=f"ProductFlowAgent_{self.line_id}",
            instructions=instructions,
            model=os.getenv("model", "gpt-4.1-mini"),
        )

    async def generate_flow_commands(
        self, factory_state: Dict[str, Any], context_type: str = "planned"
    ) -> List[Dict[str, Any]]:
        """Generate commands based on current factory state and product flow logic."""

        # Create context for the agent
        context = self._create_flow_context(factory_state, context_type)

        try:
            # Run the agent
            result = await Runner.run(self.agent, context, session=self.session)

            # Parse commands
            commands = self._parse_agent_output(result.final_output)

            # Update ongoing operations tracking
            self._update_ongoing_operations(commands)

            logger.info(f"Generated {len(commands)} product flow commands")
            return commands

        except Exception as e:
            logger.error(f"Error generating flow commands: {e}")
            return []

    def _create_flow_context(
        self, factory_state: Dict[str, Any], context_type: str
    ) -> str:
        """Create context for the product flow agent."""

        # Extract key information
        raw_material = factory_state.get("warehouse", {})
        stations = factory_state.get("stations", {})
        agvs = factory_state.get("agvs", {})
        conveyors = factory_state.get("conveyors", {})

        # Analyze current situation
        analysis = self._analyze_factory_situation(
            raw_material, stations, agvs, conveyors
        )

        context_data = {
            "context_type": context_type,
            "line_id": self.line_id,
            "timestamp": datetime.now().isoformat(),
            "factory_state": factory_state,
            "situation_analysis": analysis,
            "ongoing_operations": self.ongoing_operations,
        }

        return f"""
PRODUCT FLOW ANALYSIS - {context_type.upper()} OPERATION

Current Factory State:
{json.dumps(context_data, indent=2)}

SITUATION ANALYSIS:
{analysis["summary"]}

IMMEDIATE ACTIONS NEEDED:
{json.dumps(analysis["actions_needed"], indent=2)}

CRITICAL TASK: Generate optimal AGV commands following MANDATORY SEQUENCE RULES

SEQUENCE REQUIREMENTS:
1. EVERY command sequence MUST start with MOVE
2. NEVER send load/unload without moving to location first
3. Follow the 4-step pattern: MOVE → LOAD/UNLOAD → MOVE → LOAD/UNLOAD

PRIORITY ACTIONS:
1. Completing urgent deliveries (QualityCheck → Warehouse) - MOVE to P8 first!
2. Starting new production (RawMaterial → StationA) - MOVE to P0 first!
3. Continuing P3 double processing (Conveyor_CQ → StationB) - MOVE to P6 first!
4. Managing AGV battery levels
5. Avoiding command conflicts

GENERATE JSON ARRAY WITH PROPER MOVE-FIRST SEQUENCES!
"""

    def _analyze_factory_situation(
        self, raw_material: Dict, stations: Dict, agvs: Dict, conveyors: Dict
    ) -> Dict[str, Any]:
        """Analyze the current factory situation and identify needed actions."""

        analysis = {
            "summary": "",
            "actions_needed": [],
            "priorities": [],
            "p3_products_detected": [],
        }

        # Check for finished products ready for delivery (HIGHEST PRIORITY)
        quality_check = stations.get("QualityCheck", {})
        finished_products = quality_check.get("output_buffer", [])

        if len(finished_products) > 0:
            analysis["actions_needed"].append(
                {
                    "action": "deliver_finished_products",
                    "priority": "high",
                    "details": f"{len(finished_products)} finished products waiting in QualityCheck",
                    "products": finished_products,
                }
            )

        # Check for P3 products in Conveyor_CQ buffers (HIGH PRIORITY for continuation)
        conveyor_cq = conveyors.get("Conveyor_CQ", {})
        upper_buffer = conveyor_cq.get("upper_buffer", [])
        lower_buffer = conveyor_cq.get("lower_buffer", [])

        # Identify P3 products by checking if product_id contains 'prod_3'
        p3_products_upper = [
            p for p in upper_buffer if isinstance(p, str) and "prod_3" in p
        ]
        p3_products_lower = [
            p for p in lower_buffer if isinstance(p, str) and "prod_3" in p
        ]
        total_p3_products = p3_products_upper + p3_products_lower

        # P3 products in upper_buffer need AGV_2 for second processing
        if len(p3_products_upper) > 0:
            # Check if AGV_2 is available for P3 second processing
            agv_2_available = self._select_agv_for_p3_second_processing(agvs)

            if agv_2_available:
                analysis["actions_needed"].append(
                    {
                        "action": "continue_p3_processing",
                        "priority": "high",  # High priority because P3 products are waiting
                        "details": f"P3 products need second processing: upper={len(p3_products_upper)} (AGV_2 available)",
                        "p3_products": p3_products_upper,
                        "upper_products": p3_products_upper,
                        "required_agv": "AGV_2",
                    }
                )
            else:
                analysis["actions_needed"].append(
                    {
                        "action": "wait_for_agv_2",
                        "priority": "high",
                        "details": f"P3 products waiting: upper={len(p3_products_upper)} (AGV_2 not available)",
                        "p3_products": p3_products_upper,
                        "upper_products": p3_products_upper,
                        "required_agv": "AGV_2",
                    }
                )

            analysis["p3_products_detected"] = p3_products_upper

        # P3 products in lower_buffer (shouldn't happen normally, but handle it)
        if len(p3_products_lower) > 0:
            logger.warning(
                f"P3 products found in lower_buffer: {p3_products_lower} - this is unusual!"
            )
            analysis["actions_needed"].append(
                {
                    "action": "investigate_p3_lower_buffer",
                    "priority": "medium",
                    "details": f"Unusual: P3 products in lower_buffer={len(p3_products_lower)}",
                    "lower_products": p3_products_lower,
                }
            )

        # Check for raw materials available (HIGH PRIORITY for new production)
        raw_products = raw_material.get("buffer", [])
        if len(raw_products) > 0:
            # Identify P3 products in raw materials
            p3_raw_products = [
                p for p in raw_products if isinstance(p, str) and "prod_3" in p
            ]
            p1_p2_raw_products = [
                p
                for p in raw_products
                if isinstance(p, str) and ("prod_1" in p or "prod_2" in p)
            ]

            analysis["actions_needed"].append(
                {
                    "action": "start_new_production",
                    "priority": "high",
                    "details": f"{len(raw_products)} raw materials available (P1/P2: {len(p1_p2_raw_products)}, P3: {len(p3_raw_products)})",
                    "raw_products": raw_products,
                    "p3_raw_products": p3_raw_products,
                    "p1_p2_raw_products": p1_p2_raw_products,
                }
            )

        # Check AGV status for battery management
        for agv_id, agv_data in agvs.items():
            battery = agv_data.get("battery_level", 100)
            status = agv_data.get("status", "unknown")
            payload = agv_data.get("payload", [])
            current_point = agv_data.get("current_point", "unknown")

            if battery < 20 and status != "charging":
                analysis["actions_needed"].append(
                    {
                        "action": "emergency_charging",
                        "priority": "critical",
                        "details": f"{agv_id} battery critically low: {battery}% at {current_point}",
                        "agv_id": agv_id,
                        "battery_level": battery,
                    }
                )
            elif battery < 40 and status == "idle" and len(payload) == 0:
                analysis["actions_needed"].append(
                    {
                        "action": "preventive_charging",
                        "priority": "medium",
                        "details": f"{agv_id} battery low: {battery}% at {current_point}, should charge soon",
                        "agv_id": agv_id,
                        "battery_level": battery,
                    }
                )

        # Generate summary
        total_actions = len(analysis["actions_needed"])
        high_priority = len(
            [a for a in analysis["actions_needed"] if a["priority"] == "high"]
        )
        critical_actions = len(
            [a for a in analysis["actions_needed"] if a["priority"] == "critical"]
        )

        analysis["summary"] = (
            f"Factory Status: {total_actions} actions needed ({critical_actions} critical, {high_priority} high priority)"
        )

        return analysis

    def _parse_agent_output(self, agent_output: Any) -> List[Dict[str, Any]]:
        """Parse agent output into command list."""
        try:
            commands = []

            if isinstance(agent_output, dict):
                commands = agent_output.get("commands", [])
            elif isinstance(agent_output, str):
                # Handle JSON in markdown code blocks
                if agent_output.strip().startswith("```json"):
                    json_str = agent_output.split("```json")[1].split("```")[0].strip()
                    commands = json.loads(json_str)
                else:
                    # Try to extract JSON from potentially mixed content
                    cleaned_output = self._extract_json_from_text(agent_output)
                    commands = json.loads(cleaned_output)
            elif isinstance(agent_output, list):
                commands = agent_output

            if not isinstance(commands, list):
                logger.error(f"Agent output is not a list: {type(commands)}")
                return []

            # Validate commands
            validated_commands = []
            for cmd in commands:
                if self._validate_command(cmd):
                    validated_commands.append(cmd)
                else:
                    logger.warning(f"Invalid command filtered out: {cmd}")

            return validated_commands

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse agent output as JSON: {e}")
            logger.debug(f"Problematic output: {agent_output}")
            return []
        except Exception as e:
            logger.error(f"Error parsing agent output: {e}")
            return []

    def _extract_json_from_text(self, text: str) -> str:
        """Extract JSON from text that may contain extra content."""
        import re

        # Try to find JSON array or object in the text
        json_patterns = [
            r"\[.*?\]",  # JSON array
            r"\{.*?\}",  # JSON object
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            if matches:
                # Return the first valid JSON match
                for match in matches:
                    try:
                        json.loads(match)  # Test if it's valid JSON
                        return match
                    except json.JSONDecodeError:
                        continue

        # If no valid JSON found, return original text
        return text.strip()

    def _validate_command(self, command: Dict[str, Any]) -> bool:
        """Validate command structure and logic."""
        required_fields = ["action", "target"]

        # Check required fields
        for field in required_fields:
            if field not in command:
                logger.warning(f"Command missing required field '{field}': {command}")
                return False

        # Validate action
        valid_actions = ["move", "load", "unload", "charge"]
        if command["action"] not in valid_actions:
            logger.warning(f"Invalid action '{command['action']}': {command}")
            return False

        # Validate target AGV
        if command["target"] not in ["AGV_1", "AGV_2"]:
            logger.warning(f"Invalid target AGV '{command['target']}': {command}")
            return False

        # Validate target_point for move commands
        if command["action"] == "move":
            params = command.get("params", {})
            target_point = params.get("target_point")
            valid_points = ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"]

            if not target_point:
                logger.warning(f"Move command missing target_point: {command}")
                return False

            if target_point not in valid_points:
                logger.warning(f"Invalid target_point '{target_point}': {command}")
                return False

        # Validate charge command parameters
        if command["action"] == "charge":
            params = command.get("params", {})
            target_level = params.get("target_level", 80)

            if (
                not isinstance(target_level, (int, float))
                or target_level < 0
                or target_level > 100
            ):
                logger.warning(f"Invalid target_level for charge command: {command}")
                return False

        return True

    def _update_ongoing_operations(self, commands: List[Dict[str, Any]]):
        """Update tracking of ongoing operations."""
        for cmd in commands:
            agv_id = cmd["target"]
            action = cmd["action"]

            if action == "charge":
                if agv_id not in self.ongoing_operations["agv_charging"]:
                    self.ongoing_operations["agv_charging"].append(agv_id)
            elif action == "load":
                params = cmd.get("params", {})
                if "product_id" in params:
                    # Loading from RawMaterial
                    self.ongoing_operations["raw_material_pickup"][agv_id] = params[
                        "product_id"
                    ]
                else:
                    # Loading from QualityCheck
                    self.ongoing_operations["quality_check_delivery"][agv_id] = (
                        "finished_product"
                    )

    def _select_agv_for_p3_second_processing(self, agvs: Dict[str, Any]) -> str:
        """Select AGV for P3 second processing. MUST be AGV_2 due to upper_buffer access."""
        agv_2_data = agvs.get("AGV_2", {})
        agv_2_status = agv_2_data.get("status", "unknown")
        agv_2_battery = agv_2_data.get("battery_level", 0)

        # Check if AGV_2 is available and has sufficient battery
        if agv_2_status == "idle" and agv_2_battery > 30:
            return "AGV_2"
        elif agv_2_status == "idle" and agv_2_battery > 20:
            # AGV_2 available but low battery - still use it for P3 as it's the only option
            logger.warning(
                f"AGV_2 has low battery ({agv_2_battery}%) but needed for P3 second processing"
            )
            return "AGV_2"
        else:
            # AGV_2 not available - P3 second processing must wait
            logger.warning(
                f"AGV_2 not available for P3 second processing (status: {agv_2_status}, battery: {agv_2_battery}%)"
            )
            return None
