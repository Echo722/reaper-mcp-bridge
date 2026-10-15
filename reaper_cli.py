import sys
import asyncio
import json
from pathlib import Path

# Allow importing server.*
sys.path.insert(0, str(Path(__file__).resolve().parent))

from server.app import mcp

async def main():
    if len(sys.argv) < 2:
        print("Usage: python reaper_cli.py <tool_name> [json_args]")
        sys.exit(1)
    
    tool_name = sys.argv[1]
    kwargs = {}
    if len(sys.argv) > 2:
        try:
            kwargs = json.loads(sys.argv[2])
        except Exception as e:
            print(f"Error parsing JSON arguments: {e}", file=sys.stderr)
            sys.exit(1)
        
    try:
        res = await mcp.call_tool(tool_name, arguments=kwargs)
        # Handle different types of tool results
        if isinstance(res, list):
            out_list = []
            for item in res:
                if hasattr(item, 'text'):
                    out_list.append(item.text)
                else:
                    out_list.append(str(item))
            for out in out_list:
                try:
                    # If the content is valid JSON, pretty print it
                    parsed = json.loads(out)
                    print(json.dumps(parsed, indent=2, default=str))
                except json.JSONDecodeError:
                    print(out)
        elif hasattr(res, 'text'):
            print(res.text)
        elif isinstance(res, dict):
            print(json.dumps(res, indent=2, default=str))
        else:
            print(str(res))
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(2)

if __name__ == '__main__':
    asyncio.run(main())
