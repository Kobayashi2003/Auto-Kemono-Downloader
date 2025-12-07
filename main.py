import inspect
import os
import signal

from src import (
    API,
    Cache,
    CLIContext,
    ClashProxyPool,
    Downloader,
    ExternalLinksDownloader,
    ExternalLinksExtractor,
    Logger,
    Migrator,
    Notifier,
    NullProxyPool,
    RPCClient,
    RPCServer,
    Scheduler,
    Storage,
    Validator,
)
from src.prompt import CLIPromptSession


# Global state for interrupt handling
interrupt_count = 0
rpc_server = None


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    global interrupt_count
    interrupt_count += 1

    if interrupt_count == 1:
        print("\n\n⚠ Shutdown requested. Press Ctrl+C again to force quit.")
        raise KeyboardInterrupt
    else:
        print("\n⚠ Force quitting...")
        os._exit(1)


def check_existing_instance():
    """Check if another instance is running, connect to it if so"""
    print("Checking for existing instance...")
    client = RPCClient(port=18861)

    if client.connect():
        try:
            client.run_interactive()
        except KeyboardInterrupt:
            print("\nDisconnecting...")
        finally:
            client.close()
        return True

    return False


def initialize_services():
    """Initialize all services in dependency order"""

    notifier = Notifier(enabled=False)
    validator = Validator(data_dir="data")
    storage = Storage("data")
    config = storage.load_config()
    logger = Logger(config.logs_dir)
    cache = Cache(
        cache_dir=config.cache_dir,
        logger=logger,
        config=config,
        storage=storage
    )
    migrator = Migrator(storage=storage, cache=cache)
    external_links_extractor = ExternalLinksExtractor(cache=cache, logger=logger)
    external_links_downloader = ExternalLinksDownloader(logger=logger)

    if getattr(config, 'use_proxy', False):
        try:
            proxy_pool = ClashProxyPool(
                clash_exe=getattr(config, 'clash_exe_path', ''),
                clash_config=getattr(config, 'clash_config_path', ''),
                base_port=getattr(config, 'proxy_base_port', 7890),
                num_instances=getattr(config, 'proxy_num_instances', 10),
                temp_dir=getattr(config, 'temp_dir', 'temp'),
                skip_keywords=getattr(config, 'proxy_skip_keywords', None),
                logger=logger
            )
            logger.info(f"Proxy enabled: {proxy_pool.size()} proxies")
        except Exception as e:
            logger.error(f"Failed to initialize proxy pool: {e}")
            proxy_pool = NullProxyPool()
    else:
        proxy_pool = NullProxyPool()
        logger.info("Proxy disabled")

    api = API(logger=logger, proxy_pool=proxy_pool)

    downloader = Downloader(
        config=config,
        logger=logger,
        storage=storage,
        cache=cache,
        api=api,
        notifier=notifier
    )

    scheduler = Scheduler(
        storage=storage,
        downloader=downloader,
        global_timer=config.global_timer,
        max_workers=config.max_concurrent_artists,
        logger=logger
    )

    return {
        "logger": logger,
        "storage": storage,
        "scheduler": scheduler,
        "cache": cache,
        "api": api,
        "downloader": downloader,
        "migrator": migrator,
        "validator": validator,
        "external_links_extractor": external_links_extractor,
        "external_links_downloader": external_links_downloader,
    }


def cleanup_services(rpc_server, downloader, scheduler, proxy_pool, logger):
    """Clean up all services on shutdown"""
    if rpc_server:
        rpc_server.stop()
    downloader.stop()
    scheduler.stop()
    proxy_pool.cleanup()
    logger.info("Shutdown complete")


def parse_command(cmd_input: str) -> tuple[str, dict]:
    """Parse command with parameters (format: command:param1=value1,param2=value2)"""
    if ':' not in cmd_input:
        return (cmd_input, {})

    parts = cmd_input.split(':', 1)
    command = parts[0].strip()
    params_str = parts[1].strip()

    params = {}
    if params_str:
        for param in params_str.split(','):
            param = param.strip()
            if '=' in param:
                key, value = param.split('=', 1)
                params[key.strip()] = value.strip()

    return (command, params)


def run_cli(ctx: CLIContext):
    """CLI main loop with hot reload support for commands"""
    from src.plugins import dynamic_get

    session = CLIPromptSession(ctx.storage, lambda: dynamic_get('COMMAND_MAP', 'src/cmd.py'))

    while True:
        try:
            cmd_input = session.prompt("> ")

            if not cmd_input:
                continue

            command, params = parse_command(cmd_input)
            COMMAND_MAP = dynamic_get('COMMAND_MAP', 'src/cmd.py')
            handler = COMMAND_MAP.get(command)

            if handler:
                # Check if handler accepts the provided parameters
                sig = inspect.signature(handler)
                handler_params = set(sig.parameters.keys()) - {'ctx'}
                if params:
                    # Filter params to only include those the handler accepts
                    valid_params = {k: v for k, v in params.items() if k in handler_params}
                    invalid_params = set(params.keys()) - handler_params

                    if invalid_params:
                        print(f"Warning: Command '{command}' doesn't support parameters: {', '.join(invalid_params)}")

                    try:
                        handler(ctx, **valid_params)
                        # Record successful command with artist_id and params
                        artist_id = ctx._last_selected_artist
                        ctx._last_selected_artist = None  # Clear for next command
                        ctx.storage.add_history(command, success=True, artist_id=artist_id, params=valid_params)
                    except Exception as e:
                        # Record failed command with error message
                        artist_id = ctx._last_selected_artist
                        ctx._last_selected_artist = None  # Clear for next command
                        ctx.storage.add_history(command, success=False, artist_id=artist_id, params=valid_params, note=str(e))
                        raise
                else:
                    try:
                        handler(ctx)
                        # Record successful command with artist_id
                        artist_id = ctx._last_selected_artist
                        ctx._last_selected_artist = None  # Clear for next command
                        ctx.storage.add_history(command, success=True, artist_id=artist_id, params={})
                    except Exception as e:
                        # Record failed command with error message
                        artist_id = ctx._last_selected_artist
                        ctx._last_selected_artist = None  # Clear for next command
                        ctx.storage.add_history(command, success=False, artist_id=artist_id, params={}, note=str(e))
                        raise
            else:
                print("Unknown command. Type 'help' for available commands.")

        except KeyboardInterrupt:
            # Re-raise to allow proper cleanup
            raise
        except Exception as e:
            print(f"Error: {e}")


def main():
    """Application entry point"""
    global rpc_server

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if check_existing_instance():
        return

    services = initialize_services()

    ctx = CLIContext(
        storage=services["storage"],
        scheduler=services["scheduler"],
        cache=services["cache"],
        api=services["api"],
        downloader=services["downloader"],
        migrator=services["migrator"],
        validator=services["validator"],
        external_links_extractor=services["external_links_extractor"],
        external_links_downloader=services["external_links_downloader"],
    )

    rpc_server = RPCServer(ctx, port=18861)

    try:
        rpc_server.start()
        services["scheduler"].start()
        services["logger"].info(f"Started with {len(services['storage'].get_artists())} artists")

        # Step 6: Run CLI (main loop)
        run_cli(ctx)
    except KeyboardInterrupt:
        print("\nStopping all tasks...")
    finally:
        # Step 7: Cleanup
        cleanup_services(
            rpc_server,
            services["downloader"],
            services["scheduler"],
            services["api"].proxy_pool,
            services["logger"]
        )


if __name__ == "__main__":
    main()
