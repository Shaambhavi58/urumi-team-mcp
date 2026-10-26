#!/usr/bin/env python3
"""Independent Streamable HTTP MCP client smoke test."""
import argparse
import json
import httpx
p=argparse.ArgumentParser();p.add_argument('--url',default='http://localhost:8000/mcp');p.add_argument('--key',required=True);p.add_argument('--tool');p.add_argument('--arguments',default='{}');a=p.parse_args()
h={'Authorization':f'Bearer {a.key}','Accept':'application/json, text/event-stream','Content-Type':'application/json'}
with httpx.Client(timeout=12) as c:
 c.post(a.url,headers=h,json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'urumi-smoke-client','version':'1.0'}}}).raise_for_status()
 body={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}
 if a.tool: body={'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':a.tool,'arguments':json.loads(a.arguments)}}
 r=c.post(a.url,headers=h,json=body);r.raise_for_status();print(json.dumps(r.json(),indent=2))
