# Variant B's entire tool surface: one broad tool instead of Variant A's five
# narrow ones -- this is the actual independent variable of the study (see
# PROJECT_PLAN.md RQ1), so the schema stays deliberately minimal rather than
# hand-holding the model the way tool NAMES do for Variant A.
VARIANT_B_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "execute_python",
            "description": (
                "Runs the given Python code in a sandboxed container and returns "
                "its stdout/stderr. A read-only database connection string is "
                "available as the DATABASE_URL environment variable (connect with "
                "psycopg, already installed). Use print() for anything you want to "
                "see -- this is the only way to query the repository's data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python source code to run as a standalone script.",
                    }
                },
                "required": ["code"],
            },
        },
    }
]
