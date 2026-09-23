"""Tools package.

Phase 2: each tool module self-registers into tools/registry.py via
register(Tool). All tools are read-only by construction — they gather
evidence and return text; nothing may mutate state.
"""