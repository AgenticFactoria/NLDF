#!/usr/bin/env python3
"""
Product Flow Agent
Specialized agent that understands the complete product workflow and generates
optimal AGV commands based on the successful product flow pattern.
"""

import json
import logging
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

EXPERTISE: You understand the complete product workflow and generate optimal AGV commands.

SUCCESSFUL PRODUCT FLOW (P1/P2):
1. AGV → P0 (RawMaterial) → load specific product_id
2. AGV → P1 (StationA) → unload (automatic processing starts)
3. [AUTOMATIC] StationA → Conveyor_AB → StationB → Conveyor_BC → StationC → Conveyor_CQ → QualityCheck
4. AGV → P8 (QualityCheck) → load finished product
5. AGV → P9 (Warehouse) → unload finished product

PRODUCT FLOW (P3 - Double Processing):
1. AGV → P0 (RawMaterial) → load specific product_id (e.g., 'prod_3_75a16c3d')
2. AGV → P1 (StationA) → unload
3. [AUTOMATIC] StationA → Conveyor_AB → StationB → Conveyor_BC → StationC → Conveyor_CQ (upper_buffer)
4. **CRITICAL**: Only AGV_2 can access Conveyor_CQ upper_buffer at P6!
5. AGV_2 → P6 (Conveyor_CQ) → load same product_id from upper_buffer
6. AGV_2 → P3 (StationB) → unload (second processing cycle)
7. [AUTOMATIC] StationB → Conveyor_BC → StationC → Conveyor_CQ → QualityCheck
8. AGV → P8 (QualityCheck) → load same product_id (finished product)
9. AGV → P9 (Warehouse) → unload finished product

AGV BUFFER ACCESS RESTRICTIONS:
- AGV_1 at P6: Can only access Conveyor_CQ lower_buffer
- AGV_2 at P6: Can only access Conveyor_CQ upper_buffer
- P3 products after first processing go to upper_buffer
- Therefore: ONLY AGV_2 can handle P3 second processing!

EXACT P3 COMMAND SEQUENCE (Based on Real Factory Data):
Stage 1 (Any AGV): RawMaterial → StationA
Stage 2 (ONLY AGV_2): Conveyor_CQ upper_buffer → StationB  
Stage 3 (Any AGV): QualityCheck → Warehouse

KEY INSIGHTS:
- AGV only needed for: RawMaterial→StationA, QualityCheck→Warehouse, (P3: Conveyor_CQ→StationB)
- Stations and conveyors handle processing automatically
- Monitor RawMaterial buffer for new products to start
- Monitor QualityCheck output_buffer for finished products
- Battery management: charge when < 30%, target 80%

DECISION LOGIC:
1. HIGH PRIORITY: Finished products in QualityCheck output_buffer (deliver to warehouse)
2. HIGH PRIORITY: P3 products in Conveyor_CQ upper/lower buffer (continue double processing - critical for P3 flow)
3. HIGH PRIORITY: Raw materials available + idle AGV (start new production)
4. MEDIUM PRIORITY: AGV battery < 40% and idle (preventive charging)
5. CRITICAL: AGV battery < 20% (emergency charging)

P3 PROCESSING STAGES:
- Stage 1: RawMaterial → StationA (same as P1/P2)
- Stage 2: Conveyor_CQ upper/lower buffer → StationB (P3 specific second processing)
- Stage 3: QualityCheck → Warehouse (same as P1/P2)

IMPORTANT: P3 products MUST be picked up from Conveyor_CQ upper_buffer and delivered to StationB for second processing cycle!

COMMAND GENERATION RULES:
- Always specify product_id when loading from RawMaterial
- Use auto-detection when loading from QualityCheck (don't specify product_id)
- **CRITICAL P3 RULE**: Only AGV_2 can load P3 products from Conveyor_CQ upper_buffer at P6
- AGV_1 can only access Conveyor_CQ lower_buffer at P6 (not used for P3)
- P3 second processing MUST use AGV_2 for Conveyor_CQ → StationB transport
- Avoid command conflicts: don't send multiple AGVs to same location simultaneously
- Balance workload between available AGVs (except P3 second processing)

RESPONSE FORMAT:
Generate JSON array of commands with clear reasoning:
[
  {{
    "command_id": "flow_timestamp_action",
    "action": "move|load|unload|charge",
    "target": "AGV_1|AGV_2",
    "params": {{"target_point": "P0", "product_id": "prod_1_abc123", "target_level": 80.0}},
  }}
]

OPTIMIZATION PRINCIPLES:
- Maximize throughput by keeping production flowing
- Minimize AGV idle time
- Ensure products don't wait unnecessarily
- Balance AGV battery levels
- Prioritize order completion
"""

        return Agent(
            name=f"ProductFlowAgent_{self.line_id}",
            instructions=instructions,
            model="gpt-4.1-mini",
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

TASK: Based on the product flow logic and current factory state, generate optimal AGV commands.

Focus on:
1. Completing any urgent deliveries (QualityCheck → Warehouse)
2. Starting new production (RawMaterial → StationA) 
3. Continuing P3 double processing (Conveyor_CQ → StationB)
4. Managing AGV battery levels
5. Avoiding command conflicts

Generate JSON array of commands with clear reasoning for each action.
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

    def clear_operation(self, agv_id: str, operation_type: str):
        """Clear completed operation from tracking."""
        if operation_type == "charging":
            if agv_id in self.ongoing_operations["agv_charging"]:
                self.ongoing_operations["agv_charging"].remove(agv_id)
        elif operation_type == "raw_pickup":
            self.ongoing_operations["raw_material_pickup"].pop(agv_id, None)
        elif operation_type == "quality_delivery":
            self.ongoing_operations["quality_check_delivery"].pop(agv_id, None)

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

    def _select_best_available_agv(
        self, agvs: Dict[str, Any], exclude_agvs: List[str] = None
    ) -> str:
        """Select the best available AGV for general tasks."""
        if exclude_agvs is None:
            exclude_agvs = []

        available_agvs = []

        for agv_id in ["AGV_1", "AGV_2"]:
            if agv_id in exclude_agvs:
                continue

            agv_data = agvs.get(agv_id, {})
            status = agv_data.get("status", "unknown")
            battery = agv_data.get("battery_level", 0)

            if status == "idle" and battery > 30:
                available_agvs.append((agv_id, battery))

        if not available_agvs:
            return None

        # Sort by battery level (highest first) and return the best AGV
        available_agvs.sort(key=lambda x: x[1], reverse=True)
        return available_agvs[0][0]

    def _generate_p3_command_sequence(
        self, agv_id: str, product_id: str, stage: str
    ) -> List[Dict[str, Any]]:
        """Generate the exact P3 command sequence based on the stage."""
        commands = []
        timestamp = datetime.now().timestamp()

        if stage == "start_p3_production":
            # P3 Stage 1: RawMaterial → StationA
            commands = [
                {
                    "command_id": f"p3_start_{timestamp}_move_to_raw",
                    "action": "move",
                    "target": agv_id,
                    "params": {"target_point": "P0"},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: Move to RawMaterial for pickup",
                    "flow_stage": "p3_raw_pickup",
                },
                {
                    "command_id": f"p3_start_{timestamp}_load_raw",
                    "action": "load",
                    "target": agv_id,
                    "params": {"product_id": product_id},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: Load from RawMaterial",
                    "flow_stage": "p3_raw_pickup",
                },
                {
                    "command_id": f"p3_start_{timestamp}_move_to_station_a",
                    "action": "move",
                    "target": agv_id,
                    "params": {"target_point": "P1"},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: Move to StationA for first processing",
                    "flow_stage": "p3_station_delivery",
                },
                {
                    "command_id": f"p3_start_{timestamp}_unload_station_a",
                    "action": "unload",
                    "target": agv_id,
                    "params": {},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: Unload at StationA for first processing cycle",
                    "flow_stage": "p3_station_delivery",
                },
            ]

        elif stage == "continue_p3_processing":
            # P3 Stage 2: Conveyor_CQ → StationB (second processing) - MUST use AGV_2
            if agv_id != "AGV_2":
                logger.error(
                    f"P3 second processing attempted with {agv_id}, but only AGV_2 can access upper_buffer!"
                )
                return []

            commands = [
                {
                    "command_id": f"p3_continue_{timestamp}_move_to_conveyor_cq",
                    "action": "move",
                    "target": "AGV_2",  # Force AGV_2 for P3 second processing
                    "params": {"target_point": "P6"},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: AGV_2 move to Conveyor_CQ upper_buffer (only AGV_2 can access)",
                    "flow_stage": "p3_second_pickup",
                },
                {
                    "command_id": f"p3_continue_{timestamp}_load_conveyor_cq",
                    "action": "load",
                    "target": "AGV_2",  # Force AGV_2 for P3 second processing
                    "params": {"product_id": product_id},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: AGV_2 load from Conveyor_CQ upper_buffer",
                    "flow_stage": "p3_second_pickup",
                },
                {
                    "command_id": f"p3_continue_{timestamp}_move_to_station_b",
                    "action": "move",
                    "target": "AGV_2",  # Force AGV_2 for P3 second processing
                    "params": {"target_point": "P3"},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: AGV_2 move to StationB for second processing cycle",
                    "flow_stage": "p3_second_delivery",
                },
                {
                    "command_id": f"p3_continue_{timestamp}_unload_station_b",
                    "action": "unload",
                    "target": "AGV_2",  # Force AGV_2 for P3 second processing
                    "params": {},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: AGV_2 unload at StationB for second processing cycle",
                    "flow_stage": "p3_second_delivery",
                },
            ]

        elif stage == "finish_p3_production":
            # P3 Stage 3: QualityCheck → Warehouse
            commands = [
                {
                    "command_id": f"p3_finish_{timestamp}_move_to_quality",
                    "action": "move",
                    "target": agv_id,
                    "params": {"target_point": "P8"},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: Move to QualityCheck for finished product pickup",
                    "flow_stage": "p3_quality_pickup",
                },
                {
                    "command_id": f"p3_finish_{timestamp}_load_quality",
                    "action": "load",
                    "target": agv_id,
                    "params": {"product_id": product_id},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: Load finished product from QualityCheck",
                    "flow_stage": "p3_quality_pickup",
                },
                {
                    "command_id": f"p3_finish_{timestamp}_move_to_warehouse",
                    "action": "move",
                    "target": agv_id,
                    "params": {"target_point": "P9"},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: Move to Warehouse for final delivery",
                    "flow_stage": "p3_warehouse_delivery",
                },
                {
                    "command_id": f"p3_finish_{timestamp}_unload_warehouse",
                    "action": "unload",
                    "target": agv_id,
                    "params": {},
                    "priority": "high",
                    "reasoning": f"P3 product {product_id}: Unload finished product at Warehouse",
                    "flow_stage": "p3_warehouse_delivery",
                },
            ]

        return commands

    def _generate_p1_p2_command_sequence(
        self, agv_id: str, product_id: str, stage: str
    ) -> List[Dict[str, Any]]:
        """Generate P1/P2 command sequence."""
        commands = []
        timestamp = datetime.now().timestamp()

        if stage == "start_p1_p2_production":
            # P1/P2: RawMaterial → StationA
            commands = [
                {
                    "command_id": f"p1_p2_start_{timestamp}_move_to_raw",
                    "action": "move",
                    "target": agv_id,
                    "params": {"target_point": "P0"},
                    "priority": "high",
                    "reasoning": f"P1/P2 product {product_id}: Move to RawMaterial for pickup",
                    "flow_stage": "raw_pickup",
                },
                {
                    "command_id": f"p1_p2_start_{timestamp}_load_raw",
                    "action": "load",
                    "target": agv_id,
                    "params": {"product_id": product_id},
                    "priority": "high",
                    "reasoning": f"P1/P2 product {product_id}: Load from RawMaterial",
                    "flow_stage": "raw_pickup",
                },
                {
                    "command_id": f"p1_p2_start_{timestamp}_move_to_station_a",
                    "action": "move",
                    "target": agv_id,
                    "params": {"target_point": "P1"},
                    "priority": "high",
                    "reasoning": f"P1/P2 product {product_id}: Move to StationA for processing",
                    "flow_stage": "station_delivery",
                },
                {
                    "command_id": f"p1_p2_start_{timestamp}_unload_station_a",
                    "action": "unload",
                    "target": agv_id,
                    "params": {},
                    "priority": "high",
                    "reasoning": f"P1/P2 product {product_id}: Unload at StationA for processing",
                    "flow_stage": "station_delivery",
                },
            ]

        elif stage == "finish_p1_p2_production":
            # P1/P2: QualityCheck → Warehouse
            commands = [
                {
                    "command_id": f"p1_p2_finish_{timestamp}_move_to_quality",
                    "action": "move",
                    "target": agv_id,
                    "params": {"target_point": "P8"},
                    "priority": "high",
                    "reasoning": f"P1/P2 product {product_id}: Move to QualityCheck for finished product pickup",
                    "flow_stage": "quality_pickup",
                },
                {
                    "command_id": f"p1_p2_finish_{timestamp}_load_quality",
                    "action": "load",
                    "target": agv_id,
                    "params": {"product_id": product_id},
                    "priority": "high",
                    "reasoning": f"P1/P2 product {product_id}: Load finished product from QualityCheck",
                    "flow_stage": "quality_pickup",
                },
                {
                    "command_id": f"p1_p2_finish_{timestamp}_move_to_warehouse",
                    "action": "move",
                    "target": agv_id,
                    "params": {"target_point": "P9"},
                    "priority": "high",
                    "reasoning": f"P1/P2 product {product_id}: Move to Warehouse for final delivery",
                    "flow_stage": "warehouse_delivery",
                },
                {
                    "command_id": f"p1_p2_finish_{timestamp}_unload_warehouse",
                    "action": "unload",
                    "target": agv_id,
                    "params": {},
                    "priority": "high",
                    "reasoning": f"P1/P2 product {product_id}: Unload finished product at Warehouse",
                    "flow_stage": "warehouse_delivery",
                },
            ]

        return commands
