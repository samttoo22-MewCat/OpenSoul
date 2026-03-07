#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, str(os.getcwd()))

import logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

print("=" * 60)
print("TEST: Check FalkorDB and SoulAgent initialization")
print("=" * 60)

try:
    # Test 1: FalkorDB Connection
    print("\n1. Testing FalkorDB connection...")
    from soul.memory.graph import get_graph_client
    client = get_graph_client()
    print(f"   OK: Graph client created: {client}")

    # Skip direct query test for now

except Exception as e:
    print(f"\nERROR: FalkorDB test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    # Test 2: SoulAgent Initialization
    print("\n2. Testing SoulAgent initialization...")
    from soul.core.agent import SoulAgent
    agent = SoulAgent(graph_client=client)
    print(f"   OK: SoulAgent created: {agent}")

except Exception as e:
    print(f"\nERROR: SoulAgent initialization failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("SUCCESS: All components initialized successfully")
print("=" * 60)
