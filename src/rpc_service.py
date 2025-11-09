import rpyc
from rpyc.utils.server import ThreadedServer
import threading
import sys
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr


class DownloaderService(rpyc.Service):
    """RPC service for remote command execution"""

    # Class variable to store CLI context
    ctx = None

    def exposed_execute_command(self, cmd_input: str) -> dict:
        """Execute a command and return the result

        Args:
            cmd_input: Command string (e.g., "list:sort_by=status")

        Returns:
            dict with 'output' or 'error' key
        """
        if not self.ctx:
            return {"error": "Service not initialized"}

        try:
            from .ui import parse_command, COMMAND_MAP
            import inspect

            # Parse command
            command, params = parse_command(cmd_input)

            # Get handler
            handler = COMMAND_MAP.get(command)
            if not handler:
                return {"error": f"Unknown command: {command}"}

            # Check parameters
            sig = inspect.signature(handler)
            handler_params = set(sig.parameters.keys()) - {'ctx'}

            if params:
                valid_params = {k: v for k, v in params.items() if k in handler_params}
                invalid_params = set(params.keys()) - handler_params

                if invalid_params:
                    warning = f"Warning: Command '{command}' doesn't support parameters: {', '.join(invalid_params)}\n"
                else:
                    warning = ""
            else:
                valid_params = {}
                warning = ""

            # Capture output
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
        """Get current status"""
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
        """Start RPC server in background thread"""
        DownloaderService.ctx = self.ctx

        self.server = ThreadedServer(
            DownloaderService,
            port=self.port,
            protocol_config={
                "allow_public_attrs": True,
                "allow_pickle": True,
            }
        )

        self.thread = threading.Thread(target=self.server.start, daemon=True)
        self.thread.start()

        print(f"[RPC Server] Started on port {self.port}")

    def stop(self):
        """Stop RPC server"""
        if self.server:
            self.server.close()


class RPCClient:
    """RPC client for connecting to remote instance"""

    def __init__(self, port=18861):
        self.port = port
        self.conn = None

    def connect(self) -> bool:
        """Try to connect to RPC server"""
        try:
            self.conn = rpyc.connect(
                "localhost",
                self.port,
                config={
                    "allow_public_attrs": True,
                    "allow_pickle": True,
                }
            )
            # Test connection
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
        from prompt_toolkit import prompt
        from .ui import CommandCompleter, COMMAND_MAP

        print("[Client Mode] Connected to existing instance")
        print("Type 'help' for available commands, 'exit' to quit")

        completer = CommandCompleter(COMMAND_MAP.keys())

        while True:
            try:
                cmd_input = prompt("> ", completer=completer).strip().lower()

                if not cmd_input:
                    continue

                if cmd_input == "exit":
                    print("Disconnecting...")
                    break

                # Execute command remotely
                result = self.execute_command(cmd_input)

                # Display result
                if "error" in result:
                    print(f"Error: {result['error']}")
                elif "output" in result:
                    print(result['output'], end='')

            except KeyboardInterrupt:
                print("\nDisconnecting...")
                break
            except EOFError:
                print("\nDisconnecting...")
                break
            except Exception as e:
                print(f"Error: {e}")

        self.close()
