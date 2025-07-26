#!/usr/bin/env python3
"""
Product Flow Agent
Specialized agent that understands the complete product workflow and generates
optimal AGV commands based on the successful product flow pattern.
"""

import json
import logging
import os
from typing import Any, Dict, List

from agents import Agent, Runner, SQLiteSession
from shared_order_manager import SharedOrderManager

logger = logging.getLogger(__name__)


class ProductFlowAgent:
    """
    Specialized agent that understands product flow and generates optimal AGV commands.
    """

    def __init__(self, line_id: str, shared_order_manager: SharedOrderManager):
        self.line_id = line_id
        self.shared_order_manager = shared_order_manager
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

CRITICAL RULE: GENERATE COMMANDS FOR AVAILABLE AGVs ONLY
AGV operations take time to complete. You can send commands to different AGVs simultaneously, but only ONE command per AGV at a time.

AVAILABLE AGVs: AGV_1, AGV_2
- If both AGVs are available, you can generate up to 2 commands (one for each AGV)
- If only one AGV is available, generate only 1 command for that AGV
- NEVER send multiple commands to the same AGV

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

COMMAND SEQUENCE LOGIC:
1. If AGV needs to move to a location, send MOVE command first
2. Wait for move completion before sending LOAD/UNLOAD
3. If AGV needs to go to another location, send another MOVE command
4. Wait for move completion before next LOAD/UNLOAD

EXAMPLE SINGLE COMMANDS:

Move to RawMaterial:
{{"action": "move", "target": "AGV_1", "params": {{"target_point": "P0"}}}}

Load from RawMaterial:
{{"action": "load", "target": "AGV_1", "params": {{"product_id": "prod_1_XXXXX"}}}}

Move to StationA:
{{"action": "move", "target": "AGV_1", "params": {{"target_point": "P1"}}}}

Unload at StationA:
{{"action": "unload", "target": "AGV_1", "params": {{}}}}

Charge AGV:
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
2. HIGH: AGV has payload and is idle → complete delivery immediately
3. HIGH: Finished products in QualityCheck → deliver to warehouse
4. HIGH: P3 products in Conveyor_CQ upper_buffer → AGV_2 second processing
5. HIGH: Raw materials available → start new production
6. MEDIUM: AGV battery < 40% and idle → preventive charging

AGV PAYLOAD HANDLING:
- If AGV has payload and is at P8 (QualityCheck), load more finished products if available
- If AGV has payload and is NOT at P9 (Warehouse), move to P9 first
- If AGV has payload and is at P9, unload immediately
- AGV with payload takes priority over empty AGV operations

COMMAND VALIDATION RULES:
- Generate only ONE command per request
- If AGV is not at target location, send MOVE command first
- Load from RawMaterial (P0) specifies product_id
- Load from QualityCheck (P8) uses empty params
- P3 second processing uses AGV_2 only
- Only use valid target_point values (P0-P9)
- Charge command does not need target_point

RESPONSE FORMAT - COMMANDS FOR AVAILABLE AGVs:
For single AGV:
{{"command_id": "flow_timestamp_description", "action": "move", "target": "AGV_1", "params": {{"target_point": "P0"}}}}

For multiple AGVs (if both available):
[
  {{"command_id": "flow_timestamp_agv1", "action": "move", "target": "AGV_1", "params": {{"target_point": "P0"}}}},
  {{"command_id": "flow_timestamp_agv2", "action": "move", "target": "AGV_2", "params": {{"target_point": "P8"}}}}
]

REMEMBER: ONE COMMAND PER AGV - DIFFERENT AGVs CAN WORK SIMULTANEOUSLY!
"""

        return Agent(
            name=f"ProductFlowAgent_{self.line_id}",
            instructions=instructions,
            model=os.getenv("model", "gpt-4.1-mini"),
        )

    async def generate_commands_for_available_agvs(
        self, factory_state: Dict[str, Any], reactive_event: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """Generate commands for available AGVs based on current factory state and optional reactive event."""

        # Log reactive event context for debugging
        if reactive_event:
            event_type = reactive_event.get("type", "unknown")
            event_severity = reactive_event.get("severity", "medium")
            logger.info(
                f"Processing reactive event in ProductFlowAgent: {event_type} (severity: {event_severity})"
            )

        # Create context for the agent including reactive event info
        context = self._create_flow_context(factory_state, reactive_event)

        # Log context for debugging
        logger.debug(f"Agent context length: {len(context)}")
        logger.debug(f"Agent context preview: {context[:500]}...")

        try:
            # Run the agent
            result = await Runner.run(self.agent, context, session=self.session)

            # Check if we got a valid result
            if not result or not hasattr(result, "final_output"):
                logger.warning("Agent returned no result or invalid result structure")
                logger.warning(f"Result type: {type(result)}")
                logger.warning(f"Result content: {result}")
                return []

            # Log the raw AI output for debugging
            logger.info(f"Raw AI output: '{result.final_output}'")
            logger.info(f"AI output type: {type(result.final_output)}")
            logger.info(
                f"AI output length: {len(str(result.final_output)) if result.final_output else 0}"
            )

            # Parse commands (can be single command or list)
            commands = self._parse_agent_output(result.final_output)

            if commands:
                # Update ongoing operations tracking
                self._update_ongoing_operations(commands)
                logger.info(f"Generated {len(commands)} commands for available AGVs")
                return commands
            else:
                logger.info("No commands generated - no action needed for this line")
                # Log factory state summary to help debug why no commands were generated
                agvs = factory_state.get("agvs", {})
                warehouse = factory_state.get("warehouse", {})
                stations = factory_state.get("stations", {})

                raw_products = len(warehouse.get("buffer", []))
                quality_products = len(
                    stations.get("QualityCheck", {}).get("output_buffer", [])
                )

                logger.info(
                    f"Factory summary: Raw materials: {raw_products}, Finished products: {quality_products}"
                )
                for agv_id, agv_data in agvs.items():
                    status = agv_data.get("status", "unknown")
                    battery = agv_data.get("battery_level", 0)
                    point = agv_data.get("current_point", "unknown")
                    logger.info(f"{agv_id}: {status} at {point}, battery {battery}%")

                return []

        except Exception as e:
            logger.error(f"Error generating flow commands: {e}")
            logger.error(f"Context length: {len(context) if context else 0}")
            return []

    def _create_flow_context(
        self, factory_state: Dict[str, Any], reactive_event: Dict[str, Any] = None
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

        # Create simplified summary
        agv_summary = []
        for agv_id in ["AGV_1", "AGV_2"]:
            agv_data = agvs.get(agv_id, {})
            status = agv_data.get("status", "unknown")
            battery = agv_data.get("battery_level", 0)
            point = agv_data.get("current_point", "unknown")
            payload = agv_data.get("payload", [])
            payload_count = len(payload)

            # Determine availability and include detailed payload info
            if status == "unknown" and battery == 0:
                agv_summary.append(f"{agv_id}: AVAILABLE (startup)")
            elif status in ["idle", "moving"] and battery > 10:
                payload_info = ""
                if payload_count > 0:
                    # Show specific product IDs in payload
                    payload_info = f", carrying:[{','.join(payload)}]"
                agv_summary.append(
                    f"{agv_id}: AVAILABLE ({status}, {battery}%, @{point}, load:{payload_count}{payload_info})"
                )
            else:
                agv_summary.append(f"{agv_id}: BUSY ({status}, {battery}%)")

        # Detailed action summary with line-specific considerations
        action_summary = []
        available_agv_count = 0

        for action in analysis["actions_needed"]:
            if action["action"] == "start_new_production":
                raw_count = len(action.get("raw_products", []))
                next_products = action.get("next_products", [])
                # Show specific product IDs that this line should process
                if next_products:
                    next_product_str = ", ".join(next_products)
                    action_summary.append(
                        f"Raw materials: {raw_count} (next: {next_product_str})"
                    )
                else:
                    p1_count = len(
                        [
                            p
                            for p in action.get("p1_p2_raw_products", [])
                            if "prod_1" in p
                        ]
                    )
                    p2_count = len(
                        [
                            p
                            for p in action.get("p1_p2_raw_products", [])
                            if "prod_2" in p
                        ]
                    )
                    p3_count = len(action.get("p3_raw_products", []))
                    action_summary.append(
                        f"Raw materials: {raw_count} (P1:{p1_count}, P2:{p2_count}, P3:{p3_count})"
                    )
            elif action["action"] == "deliver_finished_products":
                finished_count = len(action.get("products", []))
                action_summary.append(f"Finished products: {finished_count}")
            elif action["action"] == "deliver_payload_to_warehouse":
                agv_id = action.get("agv_id", "unknown")
                payload_count = len(action.get("current_payload", []))
                current_point = action.get("current_point", "unknown")
                action_summary.append(
                    f"{agv_id} payload delivery: {payload_count} items from {current_point}→P9"
                )
            elif action["action"] == "unload_at_warehouse":
                agv_id = action.get("agv_id", "unknown")
                payload_count = len(action.get("current_payload", []))
                action_summary.append(f"{agv_id} unload at P9: {payload_count} items")
            elif action["action"] == "load_more_finished_products":
                agv_id = action.get("agv_id", "unknown")
                payload_count = len(action.get("current_payload", []))
                action_summary.append(
                    f"{agv_id} at P8: load more (current: {payload_count})"
                )
            elif action["action"] == "continue_p3_processing":
                p3_count = len(action.get("p3_products", []))
                action_summary.append(f"P3 2nd processing: {p3_count}")
            elif action["action"] == "emergency_charging":
                agv_id = action.get("agv_id", "unknown")
                battery = action.get("battery_level", 0)
                action_summary.append(f"{agv_id} charging: {battery}%")

        # Count available AGVs and get their detailed status
        for agv_id in ["AGV_1", "AGV_2"]:
            agv_data = agvs.get(agv_id, {})
            status = agv_data.get("status", "unknown")
            battery = agv_data.get("battery_level", 0)

            if (status == "unknown" and battery == 0) or (
                status in ["idle", "moving"] and battery > 10
            ):
                available_agv_count += 1

        # Add station status summary
        station_summary = []
        for station_id in ["StationA", "StationB", "StationC", "QualityCheck"]:
            station_data = stations.get(station_id, {})
            status = station_data.get("status", "unknown")
            buffer_count = len(station_data.get("buffer", []))
            output_count = len(station_data.get("output_buffer", []))

            if status == "processing":
                station_summary.append(f"{station_id}:processing")
            elif buffer_count > 0 or output_count > 0:
                station_summary.append(
                    f"{station_id}:products({buffer_count + output_count})"
                )
            elif status == "idle":
                station_summary.append(f"{station_id}:idle")

        # Add conveyor status for P3 products
        conveyor_summary = []
        conveyor_cq = conveyors.get("Conveyor_CQ", {})
        upper_count = len(conveyor_cq.get("upper_buffer", []))
        lower_count = len(conveyor_cq.get("lower_buffer", []))
        if upper_count > 0 or lower_count > 0:
            conveyor_summary.append(
                f"CQ_buffers:upper({upper_count}),lower({lower_count})"
            )

        # Build reactive event context if present
        reactive_context = ""
        if reactive_event:
            event_type = reactive_event.get("type", "unknown")
            event_severity = reactive_event.get("severity", "medium")
            event_data = reactive_event.get("data", {})

            # Create specific context based on event type
            if event_type == "agv_loaded_idle":
                agv_id = event_data.get("agv_id", "unknown")
                payload_count = event_data.get("payload_count", 0)
                current_point = event_data.get("current_point", "unknown")
                reactive_context = f"""

URGENT REACTIVE EVENT: {event_type} (severity: {event_severity})
{agv_id} is idle with {payload_count} products at {current_point} - MUST complete delivery immediately!
If at P8, can load more finished products. If not at P9, must move to P9. If at P9, must unload.
"""
            elif event_type == "finished_products_ready":
                station_id = event_data.get("station_id", "unknown")
                product_count = event_data.get("product_count", 0)
                reactive_context = f"""

REACTIVE EVENT: {event_type} (severity: {event_severity})
{station_id} has {product_count} finished products ready for pickup - send available AGV to P8!
"""
            elif event_type == "agv_at_quality_check_ready":
                agv_id = event_data.get("agv_id", "unknown")
                current_point = event_data.get("current_point", "unknown")
                battery_level = event_data.get("battery_level", 0)
                reactive_context = f"""

REACTIVE EVENT: {event_type} (severity: {event_severity})
{agv_id} is idle at {current_point} with {battery_level}% battery - ready to load finished products!
Check if QualityCheck has output_buffer products to load.
"""
            elif event_type == "agv_critical_battery":
                agv_id = event_data.get("agv_id", "unknown")
                battery_level = event_data.get("battery_level", 0)
                current_point = event_data.get("current_point", "unknown")
                reactive_context = f"""

CRITICAL REACTIVE EVENT: {event_type} (severity: {event_severity})
{agv_id} battery critically low ({battery_level}%) at {current_point} - MUST charge immediately!
"""
            else:
                reactive_context = f"""

REACTIVE EVENT: {event_type} (severity: {event_severity})
EVENT DETAILS: {event_data}
SPECIAL HANDLING: This is a reactive decision triggered by the above event - prioritize actions related to this event.
"""

        return f"""
LINE: {self.line_id},
STATUS: {available_agv_count} AGVs available, {len(action_summary)} actions needed{reactive_context}

AGVs: {" | ".join(agv_summary)}

ACTIONS: {" | ".join(action_summary) if action_summary else "None"}

STATIONS: {" | ".join(station_summary) if station_summary else "All idle"}

CONVEYORS: {" | ".join(conveyor_summary) if conveyor_summary else "idle"}

DECISION LOGIC FOR THIS LINE:
1. Emergency: Battery < 20% → charge
2. High: Finished products → move to P8, then load, then move to P9, then unload
3. High: P3 upper_buffer → AGV_2 move to P6, then load specific P3 product, then move to P3, then unload
4. High: Raw materials → move to P0, then load specific product ID, then move to P1, then unload
5. Medium: Position AGVs optimally

CRITICAL FLOW: AGV idle with payload at P8 → move to P9 → unload finished products
When AGV is at P8 and QualityCheck has output_buffer of finished P1/P2 products, AGV should load them immediately.

IMPORTANT: When loading from P0 (RawMaterial), specify the exact product_id in load command
Example: [{{"command_id":"cmd_123","action":"load","target":"AGV_1","params":{{"product_id":"prod_1_abc123"}}}}]

RESPOND with the JSON Block First and then an explanation after to detail the reasoning for the command: [] or [{{"command_id":"cmd_123","action":"move","target":"AGV_X","params":{{"target_point":"P0"}}}}]
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
            # Get products actually assigned to this line from order management
            line_assigned_products = self._get_line_assigned_raw_products(raw_products)

            if line_assigned_products:
                # Identify P3 products in line-assigned materials
                p3_raw_products = [
                    p
                    for p in line_assigned_products
                    if isinstance(p, str) and "prod_3" in p
                ]
                p1_p2_raw_products = [
                    p
                    for p in line_assigned_products
                    if isinstance(p, str) and ("prod_1" in p or "prod_2" in p)
                ]

                analysis["actions_needed"].append(
                    {
                        "action": "start_new_production",
                        "priority": "high",
                        "details": f"{len(line_assigned_products)} raw materials assigned to {self.line_id} (P1/P2: {len(p1_p2_raw_products)}, P3: {len(p3_raw_products)})",
                        "raw_products": line_assigned_products,  # Only products assigned to this line
                        "next_products": line_assigned_products[
                            :3
                        ],  # First 3 assigned products
                        "p3_raw_products": p3_raw_products,
                        "p1_p2_raw_products": p1_p2_raw_products,
                    }
                )

        # Check AGV status for payload delivery and battery management (HIGHEST PRIORITY for loaded AGVs)
        for agv_id, agv_data in agvs.items():
            battery = agv_data.get("battery_level", 100)
            status = agv_data.get("status", "unknown")
            payload = agv_data.get("payload", [])
            current_point = agv_data.get("current_point", "unknown")

            # HIGHEST PRIORITY: AGV with payload needs to complete delivery
            if len(payload) > 0:
                if current_point == "P8" and status == "idle":
                    # AGV at QualityCheck with payload - can load more finished products if available
                    analysis["actions_needed"].append(
                        {
                            "action": "load_more_finished_products",
                            "priority": "high",
                            "details": f"{agv_id} at P8 with payload {payload} - can load more finished products",
                            "agv_id": agv_id,
                            "current_payload": payload,
                            "current_point": current_point,
                        }
                    )
                elif current_point != "P9" and status in ["idle", "moving"]:
                    # AGV with payload not at warehouse - must move to P9
                    analysis["actions_needed"].append(
                        {
                            "action": "deliver_payload_to_warehouse",
                            "priority": "high",
                            "details": f"{agv_id} has payload {payload} at {current_point} - must deliver to P9",
                            "agv_id": agv_id,
                            "current_payload": payload,
                            "current_point": current_point,
                        }
                    )
                elif current_point == "P9" and status == "idle":
                    # AGV at warehouse with payload - must unload
                    analysis["actions_needed"].append(
                        {
                            "action": "unload_at_warehouse",
                            "priority": "high",
                            "details": f"{agv_id} at P9 with payload {payload} - must unload",
                            "agv_id": agv_id,
                            "current_payload": payload,
                            "current_point": current_point,
                        }
                    )

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

    def _get_line_assigned_raw_products(self, all_raw_products: List[str]) -> List[str]:
        """Get raw products that are assigned to this specific line."""
        if not self.shared_order_manager:
            # Fallback: distribute products by line index to avoid conflicts
            line_index = int(self.line_id[-1]) - 1  # line1=0, line2=1, line3=2
            return [p for i, p in enumerate(all_raw_products) if i % 3 == line_index]

        try:
            # Get orders assigned to this line
            line_orders = self.shared_order_manager.get_orders_for_line(self.line_id)

            # Determine what product types this line needs to produce
            needed_product_types = []
            for order in line_orders:
                for product in order.products:
                    if hasattr(product, "product_type") and hasattr(product, "status"):
                        # Only consider products that are still pending (need raw materials)
                        if product.status.value == "pending":
                            product_type_str = product.product_type.value  # P1, P2, P3
                            needed_product_types.append(product_type_str)

            logger.info(
                f"Line {self.line_id} needs product types: {needed_product_types}"
            )

            # Match raw materials to needed product types
            assigned_raw_products = []
            needed_types_copy = (
                needed_product_types.copy()
            )  # Don't modify original list

            for raw_product_id in all_raw_products:
                # Extract product type from raw material ID (e.g., prod_1_abc -> P1)
                if "prod_1" in raw_product_id and "P1" in needed_types_copy:
                    assigned_raw_products.append(raw_product_id)
                    needed_types_copy.remove("P1")  # Remove one instance
                elif "prod_2" in raw_product_id and "P2" in needed_types_copy:
                    assigned_raw_products.append(raw_product_id)
                    needed_types_copy.remove("P2")
                elif "prod_3" in raw_product_id and "P3" in needed_types_copy:
                    assigned_raw_products.append(raw_product_id)
                    needed_types_copy.remove("P3")

            # If we still have unmatched needed types, try to get any available materials of those types
            if needed_types_copy:  # Still have unmatched product types
                logger.info(
                    f"Line {self.line_id} still needs {needed_types_copy} but no matching raw materials found"
                )

                # Try to get any remaining materials of the needed types (first-come-first-served)
                for raw_product_id in all_raw_products:
                    if (
                        raw_product_id not in assigned_raw_products
                    ):  # Not already assigned
                        if "prod_1" in raw_product_id and "P1" in needed_types_copy:
                            assigned_raw_products.append(raw_product_id)
                            needed_types_copy.remove("P1")
                        elif "prod_2" in raw_product_id and "P2" in needed_types_copy:
                            assigned_raw_products.append(raw_product_id)
                            needed_types_copy.remove("P2")
                        elif "prod_3" in raw_product_id and "P3" in needed_types_copy:
                            assigned_raw_products.append(raw_product_id)
                            needed_types_copy.remove("P3")

            # Final fallback: if still no assignments and this line has orders, distribute by index
            if not assigned_raw_products and needed_product_types:
                logger.warning(
                    f"Line {self.line_id} has orders but no matching raw materials, using index distribution"
                )
                line_index = int(self.line_id[-1]) - 1
                assigned_raw_products = [
                    p for i, p in enumerate(all_raw_products) if i % 3 == line_index
                ]

            return assigned_raw_products

        except Exception as e:
            logger.warning(f"Error getting line-assigned products: {e}")
            # Fallback: distribute products by line index
            line_index = int(self.line_id[-1]) - 1
            return [p for i, p in enumerate(all_raw_products) if i % 3 == line_index]

    def _get_available_agvs_info(self, agvs: Dict[str, Any]) -> str:
        """Get information about which AGVs are available for commands."""
        available_info = []

        for agv_id in ["AGV_1", "AGV_2"]:
            agv_data = agvs.get(agv_id, {})
            status = agv_data.get("status", "unknown")
            battery = agv_data.get("battery_level", 0)
            current_point = agv_data.get("current_point", "unknown")
            payload = agv_data.get("payload", [])

            # If AGV data is missing or invalid, assume it's available (factory might be starting up)
            if status == "unknown" and battery == 0:
                logger.warning(
                    f"{agv_id} has unknown status - assuming available for startup"
                )
                available_info.append(f"{agv_id}: AVAILABLE (startup mode)")
            # Check if AGV is available for new commands
            elif (
                status in ["idle", "moving"]
                and agv_id not in self.ongoing_operations["agv_charging"]
                and battery > 10
            ):
                available_info.append(
                    f"{agv_id}: AVAILABLE (status={status}, battery={battery}%, at={current_point}, payload={len(payload)})"
                )
            else:
                available_info.append(
                    f"{agv_id}: BUSY (status={status}, battery={battery}%)"
                )

        return " | ".join(available_info)

    def _parse_agent_output(self, agent_output: Any) -> List[Dict[str, Any]]:
        """Parse agent output into command list (can be single command or multiple)."""
        try:
            commands = []

            # Handle empty or None output
            if not agent_output:
                logger.info("Agent returned empty output - no commands needed")
                return []

            if isinstance(agent_output, dict):
                # Direct command object - wrap in list
                commands = [agent_output]
            elif isinstance(agent_output, str):
                # Clean up the string
                agent_output = agent_output.strip()

                if not agent_output:
                    logger.info("Agent returned empty string - no commands needed")
                    return []

                # Log what we're trying to parse
                logger.info(
                    f"Attempting to parse string output: '{agent_output[:200]}...'"
                )

                # Handle JSON in markdown code blocks
                if agent_output.startswith("```json"):
                    logger.info("Found JSON markdown block")
                    json_str = agent_output.split("```json")[1].split("```")[0].strip()
                    if not json_str:
                        logger.info("Empty JSON block - no commands needed")
                        return []
                    parsed = json.loads(json_str)
                else:
                    # Try to extract JSON from potentially mixed content
                    logger.info("Extracting JSON from mixed content")
                    cleaned_output = self._extract_json_from_text(agent_output)
                    if not cleaned_output:
                        logger.warning(f"No JSON found in output: '{agent_output}'")
                        return []
                    logger.info(f"Extracted JSON: '{cleaned_output}'")
                    parsed = json.loads(cleaned_output)

                # Handle both single command and array
                if isinstance(parsed, list):
                    commands = parsed
                elif isinstance(parsed, dict):
                    commands = [parsed]
            elif isinstance(agent_output, list):
                commands = agent_output

            # Handle empty command list
            if not commands:
                logger.info("No commands in parsed output")
                logger.info(
                    f"Parsed data was: {parsed if 'parsed' in locals() else 'No parsed data'}"
                )
                return []

            # Validate commands and ensure no duplicate AGV targets
            validated_commands = []
            used_agvs = set()

            for cmd in commands:
                if self._validate_command(cmd):
                    agv_target = cmd.get("target")
                    if agv_target not in used_agvs:
                        validated_commands.append(cmd)
                        used_agvs.add(agv_target)
                    else:
                        logger.warning(
                            f"Duplicate AGV target {agv_target} filtered out: {cmd}"
                        )
                else:
                    logger.warning(f"Invalid command filtered out: {cmd}")

            return validated_commands

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse agent output as JSON: {e}")
            logger.error(f"Raw agent output: '{agent_output}'")
            logger.error(f"Output type: {type(agent_output)}")
            logger.error(
                f"Output length: {len(str(agent_output)) if agent_output else 0}"
            )
            return []
        except Exception as e:
            logger.error(f"Error parsing agent output: {e}")
            logger.error(f"Raw agent output: '{agent_output}'")
            return []

    def _extract_json_from_text(self, text: str) -> str:
        """Extract JSON from text that may contain extra content."""
        import re

        if not text or not text.strip():
            return ""

        text = text.strip()

        # If it already looks like JSON, return it
        if (text.startswith("[") and text.endswith("]")) or (
            text.startswith("{") and text.endswith("}")
        ):
            return text

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

        # If no valid JSON found, return empty string
        logger.warning(f"No valid JSON found in text: '{text[:100]}...'")
        return ""

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
