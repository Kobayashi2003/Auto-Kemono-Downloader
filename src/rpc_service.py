import inspect
import threading
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

import rpyc
from rpyc.utils.server import ThreadedServer
from prompt_toolkit import prompt


class DownloaderService(rpyc.Service):
    """RPC service - supports only non-interactive commands"""

    ctx = None
    ALLOWED_COMMANDS = {'help', 'list', 'tasks'}

    def exposed_execute_command(self, cmd_input: str) -> dict:
        """Execute command and return result dict"""
        if not self.ctx:
            return {"error": "Service not initialized"}

        try:
            from .ui import parse_command, COMMAND_MAP

            command, params = parse_command(cmd_input)

            if command not in self.ALLOWED_COMMANDS:
                allowed = ', '.join(sorted(self.ALLOWED_COMMANDS))
                return {"error": f"Command '{command}' is not supported in RPC mode. Only {allowed} are available."}

            handler = COMMAND_MAP.get(command)
            if not handler:
                return {"error": f"Unknown command: {command}"}

            sig = inspect.signature(handler)
            handler_params = set(sig.parameters.keys()) - {'ctx'}

            if params:
                valid_params = {k: v for k, v in params.items() if k in handler_params}
                invalid_params = set(params.keys()) - handler_params
                warning = f"Warning: '{command}' doesn't support parameters: {', '.join(invalid_params)}\n" if invalid_params else ""
            else:
                valid_params = {}
                warning = ""

            output_buffer = StringIO()
            error_buffer = StringIO()

            with redirect_stdout(output_buffer), redirect_stderr(error_buffer):
                try:
                    handler(self.ctx, **valid_params)
                except Exception as e:
                    return {"error": f"{warning}Command execution failed: {str(e)}"}

            output = output_buffer.getvalue()
            errors = error_buffer.getvalue()

            if errors:
                return {"error": warning + errors}

            return {"output": warning + output if output else warning + "Command executed successfully"}

        except Exception as e:
            return {"error": f"Failed to execute command: {str(e)}"}

    def exposed_get_status(self) -> dict:
        """Get scheduler status"""
        if not self.ctx:
            return {"error": "Service not initialized"}

        try:
            status = self.ctx.scheduler.get_queue_status()
            return {
                "queued": status.queued,
                "running": status.running,
                "completed": status.completed
            }
        except Exception as e:
            return {"error": str(e)}

    def exposed_ping(self) -> str:
        """Health check"""
        return "pong"

class RPCServer:
    """RPC server wrapper"""

    def __init__(self, ctx, port=18861):
        self.ctx = ctx
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        """Start server in background thread"""
        DownloaderService.ctx = self.ctx
        self.server = ThreadedServer(
            DownloaderService,
            port=self.port,
            protocol_config={"allow_public_attrs": True, "allow_pickle": True}
        )
        self.thread = threading.Thread(target=self.server.start, daemon=True)
        self.thread.start()
        print(f"[RPC Server] Started on port {self.port}")

    def stop(self):
        """Stop server"""
        if self.server:
            self.server.close()


class RPCClient:
    """RPC client for connecting to remote instance"""

    def __init__(self, port=18861):
        self.port = port
        self.conn = None

    def connect(self) -> bool:
        """Connect to RPC server"""
        try:
            self.conn = rpyc.connect(
                "localhost",
                self.port,
                config={"allow_public_attrs": True, "allow_pickle": True}
            )
            self.conn.root.ping()
            return True
        except Exception:
            return False

    def execute_command(self, cmd_input: str) -> dict:
        """Execute command on remote instance"""
        if not self.conn:
            return {"error": "Not connected"}
        try:
            return self.conn.root.execute_command(cmd_input)
        except Exception as e:
            return {"error": f"RPC call failed: {str(e)}"}

    def get_status(self) -> dict:
        """Get status from remote instance"""
        if not self.conn:
            return {"error": "Not connected"}
        try:
            return self.conn.root.get_status()
        except Exception as e:
            return {"error": f"RPC call failed: {str(e)}"}

    def close(self):
        """Close connection"""
        if self.conn:
            self.conn.close()

    def run_interactive(self):
        """Run interactive client mode"""
        from .ui import CommandCompleter

        print("[Client Mode] Connected to existing instance")
        print("Available commands: help, list, tasks, exit")
        print("Note: Interactive commands are not supported in RPC mode\n")

        completer = CommandCompleter(['help', 'list', 'tasks', 'exit'])

        while True:
            try:
                cmd_input = prompt("> ", completer=completer).strip().lower()

                if not cmd_input:
                    continue

                if cmd_input == "exit":
                    print("Disconnecting...")
                    break

                result = self.execute_command(cmd_input)

                if "error" in result:
                    print(f"Error: {result['error']}")
                elif "output" in result:
                    print(result['output'], end='')

            except (KeyboardInterrupt, EOFError):
                print("\nDisconnecting...")
                break
            except Exception as e:
                print(f"Error: {e}")

        self.close()
