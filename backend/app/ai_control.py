"""
Prescriptive Optimization & Closed-Loop Actuation Agent.
Evaluates generator loads and thermal rates, returning UI advice and actuator MQTT payloads.
"""

from typing import Any, Dict, List, Optional


class PrescriptiveControlAgent:
    def evaluate_optimal_setpoints(
        self, payload: Dict[str, Any], predictions: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculates energy optimization control recommendations."""
        gen_burn_rate = (
            predictions.get("derived_insights", {})
            .get("operational_summary", {})
            .get("generator_burn_rate_lph", 0.0)
        )
        heating_burn_rate = (
            predictions.get("derived_insights", {})
            .get("operational_summary", {})
            .get("heating_burn_rate_lph", 0.0)
        )

        actions = []
        control_commands = []

        # Rule 1: Thermal Over-consumption Adjustment
        if heating_burn_rate > gen_burn_rate * 1.5:
            actions.append({
                "target": "hvac_thermal_loop",
                "recommended_setpoint_c": 18.5,
                "reason": "High thermal dissipation relative to electrical output. Lowering zone temp target by 1.5°C saves ~8% fuel burn.",
            })
            control_commands.append({
                "actuator": "hvac_thermal_loop",
                "command": "SET_TEMPERATURE",
                "target_value": 18.5,
            })

        # Rule 2: Generator Load Balancing
        if gen_burn_rate > 25.0:
            actions.append({
                "target": "generator_load_balancing",
                "recommended_mode": "ECO_STAGGERED",
                "reason": "Generator load exceeds 25L/h threshold. Stagger secondary non-essential heating loads.",
            })
            control_commands.append({
                "actuator": "generator_balancer",
                "command": "ENABLE_STAGGERED_MODE",
                "target_value": "ECO_STAGGERED",
            })

        return {
            "prescriptive_mode": "ACTIVE",
            "suggested_actions": actions,
            "actuator_commands": control_commands,
            "projected_fuel_savings_lph": round(
                (heating_burn_rate + gen_burn_rate) * 0.08, 2
            )
            if actions
            else 0.0,
        }


control_agent = PrescriptiveControlAgent()