#!/usr/bin/env python3
"""Quick test for buffer length fix"""


def test_buffer_length_handling():
    # Test the fixed buffer length logic
    test_cases = [
        {"buffer": None, "upper_buffer": None, "lower_buffer": None},
        {"buffer": [], "upper_buffer": ["item1"], "lower_buffer": None},
        {"buffer": ["item1", "item2"], "upper_buffer": [], "lower_buffer": ["item3"]},
    ]

    for i, parsed_data in enumerate(test_cases):
        print(f"Test case {i + 1}: {parsed_data}")

        try:
            # This is the fixed logic from mqtt_listener_manager.py
            buffer_len = len(parsed_data["buffer"]) if parsed_data.get("buffer") else 0
            upper_len = (
                len(parsed_data["upper_buffer"])
                if parsed_data.get("upper_buffer")
                else 0
            )
            lower_len = (
                len(parsed_data["lower_buffer"])
                if parsed_data.get("lower_buffer")
                else 0
            )

            print(
                f"✅ Success: buffer={buffer_len}, upper={upper_len}, lower={lower_len}"
            )
        except Exception as e:
            print(f"❌ Failed: {e}")
        print()


if __name__ == "__main__":
    test_buffer_length_handling()
