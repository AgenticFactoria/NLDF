#!/usr/bin/env python3
"""Quick test for JSON parsing fix"""

import sys

sys.path.append("src")
from product_flow_agent import ProductFlowAgent


def test_json_parsing():
    agent = ProductFlowAgent("line1")

    # Test case 1: JSON with extra data (the error we were seeing)
    test_json_with_extra = """[{"action": "move", "agv_id": "AGV_1"}]
Extra text after JSON that was causing the error
More extra content"""

    print("Testing JSON with extra data...")
    try:
        result = agent._parse_agent_output(test_json_with_extra)
        print(f"✅ Success: Parsed {len(result)} commands")
        print(f"   Command: {result[0] if result else 'None'}")
    except Exception as e:
        print(f"❌ Failed: {e}")

    # Test case 2: Normal JSON
    normal_json = '[{"action": "move", "agv_id": "AGV_2"}]'
    print("\nTesting normal JSON...")
    try:
        result = agent._parse_agent_output(normal_json)
        print(f"✅ Success: Parsed {len(result)} commands")
    except Exception as e:
        print(f"❌ Failed: {e}")

    # Test case 3: JSON in markdown
    markdown_json = """```json
[{"action": "pickup", "agv_id": "AGV_1"}]
```"""
    print("\nTesting JSON in markdown...")
    try:
        result = agent._parse_agent_output(markdown_json)
        print(f"✅ Success: Parsed {len(result)} commands")
    except Exception as e:
        print(f"❌ Failed: {e}")


if __name__ == "__main__":
    test_json_parsing()
