"""
MC-0004 Agent Runtime — Bridges DISPATCHED → COMPLETED.
Creates short-lived agents with tools. Conforms to RTA-0001 meta-model.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, Optional
import json, hashlib, time, subprocess, os, sys, traceback

# ═══════════════════════════════════════════════════════════
# TOOL INTERFACE — Pluggable tool model
# ═══════════════════════════════════════════════════════════

class Tool(Protocol):
    """Pluggable tool interface. Extend without modifying runtime."""
    name: str
    
    def execute(self, params: dict) -> dict:
        """Execute tool. Returns structured result."""
        ...

@dataclass
class ToolResult:
    success: bool
    output: str
    error: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    metadata: dict = field(default_factory=dict)

@dataclass
class AgentEvidence:
    agent_id: str
    task_id: str
    goal: str
    tools_used: list[str]
    start_time: str
    end_time: str
    duration_ms: int
    result: dict
    errors: list[str]
    evidence_hash: str

# ═══════════════════════════════════════════════════════════
# BUILT-IN TOOLS
# ═══════════════════════════════════════════════════════════

class ShellTool:
    name = "shell"
    
    def execute(self, params: dict) -> ToolResult:
        cmd = params.get("command", "")
        if not cmd:
            return ToolResult(False, "", "No command provided")
        
        start = time.time()
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            duration = int((time.time() - start) * 1000)
            return ToolResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr.strip(),
                exit_code=result.returncode,
                duration_ms=duration,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(False, "", "Command timed out after 30s", -1)
        except Exception as e:
            return ToolResult(False, "", str(e), -1)

class FileTool:
    name = "filesystem"
    
    def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "read")
        path = params.get("path", "")
        
        start = time.time()
        try:
            if action == "read":
                with open(path, 'r') as f:
                    content = f.read(10000)
                duration = int((time.time() - start) * 1000)
                return ToolResult(True, content, duration_ms=duration)
            elif action == "write":
                content = params.get("content", "")
                os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
                with open(path, 'w') as f:
                    f.write(content)
                duration = int((time.time() - start) * 1000)
                return ToolResult(True, f"Written {len(content)} bytes to {path}", duration_ms=duration)
            elif action == "exists":
                exists = os.path.exists(path)
                return ToolResult(True, str(exists))
            else:
                return ToolResult(False, "", f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(False, "", str(e), -1)

class HttpTool:
    name = "http"
    
    def execute(self, params: dict) -> ToolResult:
        url = params.get("url", "")
        method = params.get("method", "GET")
        headers = params.get("headers", {})
        body = params.get("body")
        
        start = time.time()
        try:
            import urllib.request, urllib.error
            data = json.dumps(body).encode() if body else None
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode('utf-8', errors='replace')[:5000]
            duration = int((time.time() - start) * 1000)
            return ToolResult(True, content, duration_ms=duration, 
                             metadata={"status": resp.status})
        except urllib.error.HTTPError as e:
            return ToolResult(False, e.read().decode('utf-8', errors='replace')[:1000], 
                             str(e), e.code)
        except Exception as e:
            return ToolResult(False, "", str(e), -1)

class PythonTool:
    name = "python"
    
    def execute(self, params: dict) -> ToolResult:
        code = params.get("code", "")
        if not code:
            return ToolResult(False, "", "No code provided")
        
        start = time.time()
        try:
            namespace = {}
            exec(code, {"__builtins__": __builtins__}, namespace)
            output = namespace.get('__result__', namespace.get('output', str(namespace)))
            duration = int((time.time() - start) * 1000)
            return ToolResult(True, str(output)[:5000], duration_ms=duration)
        except Exception as e:
            return ToolResult(False, "", traceback.format_exc()[:2000], -1)

class GitTool:
    name = "git"
    
    def execute(self, params: dict) -> ToolResult:
        action = params.get("action", "status")
        repo = params.get("repo", ".")
        
        start = time.time()
        try:
            if action == "status":
                result = subprocess.run("git status --short", shell=True, cwd=repo,
                                       capture_output=True, text=True, timeout=10)
            elif action == "tag":
                tag = params.get("tag", "")
                result = subprocess.run(f'git tag {tag}', shell=True, cwd=repo,
                                       capture_output=True, text=True, timeout=10)
            elif action == "commit":
                msg = params.get("message", "commit")
                result = subprocess.run(f'git add -A && git commit -m "{msg}"', shell=True, 
                                       cwd=repo, capture_output=True, text=True, timeout=10)
            else:
                return ToolResult(False, "", f"Unknown action: {action}")
            
            duration = int((time.time() - start) * 1000)
            return ToolResult(result.returncode == 0, result.stdout.strip(),
                             result.stderr.strip(), result.returncode, duration)
        except Exception as e:
            return ToolResult(False, "", str(e), -1)

class BrowserTool:
    name = "browser"
    
    def execute(self, params: dict) -> ToolResult:
        url = params.get("url", "")
        action = params.get("action", "screenshot")
        
        start = time.time()
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=15000)
                
                if action == "screenshot":
                    path = params.get("path", "/tmp/screenshot.png")
                    page.screenshot(path=path)
                    result_text = f"Screenshot saved to {path}"
                elif action == "content":
                    result_text = page.content()[:5000]
                elif action == "text":
                    result_text = page.locator('body').text_content()[:5000]
                else:
                    result_text = page.title()
                
                browser.close()
            duration = int((time.time() - start) * 1000)
            return ToolResult(True, result_text, duration_ms=duration)
        except ImportError:
            return ToolResult(False, "", "Playwright not installed")
        except Exception as e:
            return ToolResult(False, "", str(e)[:2000], -1)

# ═══════════════════════════════════════════════════════════
# AGENT RUNTIME
# ═══════════════════════════════════════════════════════════

class AgentRuntime:
    """Creates short-lived agents. Bridges DISPATCHED → COMPLETED."""
    
    def __init__(self):
        self.tools: dict[str, Tool] = {}
        self.agents: dict[str, dict] = {}
        self.events: list[dict] = []
        self._register_default_tools()
    
    def _register_default_tools(self):
        for tool_cls in [ShellTool, FileTool, HttpTool, PythonTool, GitTool, BrowserTool]:
            tool = tool_cls()
            self.register_tool(tool.name, tool)
    
    def register_tool(self, name: str, tool: Tool):
        self.tools[name] = tool
    
    def create_agent(self, dispatch_command: dict) -> str:
        """Create agent from dispatch command. Returns agent_id."""
        agent_id = f"agent-{dispatch_command['task_id']}-{len(self.agents)+1}"
        
        agent = {
            "agent_id": agent_id,
            "task_id": dispatch_command["task_id"],
            "goal": dispatch_command.get("goal", ""),
            "tools_requested": dispatch_command.get("tools", []),
            "state": "created",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "evidence": None,
            "error": None,
        }
        self.agents[agent_id] = agent
        self._publish("agent.created", {"agent_id": agent_id, "task_id": dispatch_command["task_id"]})
        return agent_id
    
    def execute(self, agent_id: str) -> AgentEvidence:
        """Execute agent's goal with available tools."""
        agent = self.agents.get(agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")
        
        agent["state"] = "executing"
        start_time = datetime.now(timezone.utc)
        start_ms = time.time()
        
        goal = agent["goal"]
        errors = []
        results = {}
        tools_used = []
        
        # If goal is a shell command, execute directly
        if goal.startswith("$ ") or goal.startswith("run:") or goal.startswith("Run:"):
            cmd = goal.split("$ ", 1)[-1] if "$ " in goal else goal.split(":", 1)[-1].strip()
            result = self.tools["shell"].execute({"command": cmd})
            tools_used.append("shell")
            results["shell"] = {
                "success": result.success,
                "output": result.output[:1000],
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
            }
            if not result.success:
                errors.append(result.error)
        
        # If goal mentions a URL, try HTTP
        elif "http://" in goal.lower() or "https://" in goal.lower():
            import re
            urls = re.findall(r'https?://[^\s]+', goal)
            for url in urls:
                result = self.tools["http"].execute({"url": url, "method": "GET"})
                tools_used.append("http")
                results["http"] = {
                    "url": url,
                    "success": result.success,
                    "output": result.output[:1000],
                    "status": result.metadata.get("status", 0),
                }
        
        # If goal specifies a tool, use it
        for tool_name in agent["tools_requested"]:
            if tool_name in self.tools and tool_name not in tools_used:
                try:
                    result = self.tools[tool_name].execute({"action": "default"})
                    tools_used.append(tool_name)
                    results[tool_name] = {"success": result.success}
                except Exception as e:
                    errors.append(f"Tool {tool_name}: {e}")
        
        end_time = datetime.now(timezone.utc)
        duration_ms = int((time.time() - start_ms) * 1000)
        
        evidence = AgentEvidence(
            agent_id=agent_id,
            task_id=agent["task_id"],
            goal=goal,
            tools_used=tools_used,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            duration_ms=duration_ms,
            result=results,
            errors=errors,
            evidence_hash="",
        )
        evidence.evidence_hash = hashlib.sha256(
            json.dumps(evidence.__dict__, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
        
        agent["state"] = "completed" if not errors else "failed"
        agent["evidence"] = evidence
        agent["error"] = "; ".join(errors) if errors else None
        
        event_type = "agent.completed" if not errors else "agent.failed"
        self._publish(event_type, {"agent_id": agent_id, "task_id": agent["task_id"], 
                                    "duration_ms": duration_ms, "success": not errors})
        self._publish("evidence.produced", {"agent_id": agent_id, "evidence_hash": evidence.evidence_hash})
        
        return evidence
    
    def status(self) -> dict:
        return {
            "agents": {
                "total": len(self.agents),
                "created": sum(1 for a in self.agents.values() if a["state"] == "created"),
                "executing": sum(1 for a in self.agents.values() if a["state"] == "executing"),
                "completed": sum(1 for a in self.agents.values() if a["state"] == "completed"),
                "failed": sum(1 for a in self.agents.values() if a["state"] == "failed"),
            },
            "tools": list(self.tools.keys()),
            "events": len(self.events),
        }
    
    def _publish(self, event_type: str, data: dict):
        self.events.append({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
