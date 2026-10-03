# AI_USE.md - HW5

## 1. What I used an AI assistant for, and what I did myself

I used an AI assistant to help me understand what each part of the assignment
was asking for and why, working through it one part at a time. It also edited the written documents from my results and screenshots.

I ran every command on my own machine, in my `data260` environment. I ran the
migration against my own MySQL database, tested each part in Postman, the MCP
Inspector and the terminal, ran the fault-injection experiment, the test suite
and the agent with my local qwen3:1.7b model, and took every screenshot. Every
number in METRICS.md and the report comes from those runs. I checked every
result against the assignment before moving on.

## 2. One AI-produced output that was wrong

The first version of the meals MCP server did not start on my machine. The
generated file imported `FastMCP` from `mcp.server.fastmcp`, and the install
command I was given was `pip install "mcp[cli]"` with no version.

## 3. How I detected the problem

I ran `mcp dev mcp_servers/meals_server.py` and it stopped with a traceback
ending in `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. The
message itself explained that pip had installed MCP 2.x, where FastMCP was
renamed. The code had been written for version 1.

## 4. What I changed, and why it works now

I installed the version 1 SDK with `pip install "mcp[cli]<2"`, confirmed the
import with a one-line check, and ran `mcp dev` again. The Inspector opened and
listed all four tools. It works because version 1 still has the `FastMCP`
class, which is also the class the assignment names.

A second thing I checked rather than assumed: the agent scenario meant to show
the safety rule (S4) came back as `completed` with zero tool calls, because the
model refused the request on its own. I saw this in the scenario table, so I
added scenario S6, which tells the model to make the call, and that run ended
in `safety_block`.
