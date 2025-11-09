import os
import signal

from src import API, CLI, Cache, Downloader, Logger, Migrator, Notifier, Scheduler, Storage, Validator, ClashProxyPool, NullProxyPool, RPCServer, RPCClient


# Global state for interrupt handling
interrupt_count = 0
rpc_server = None


def signal_handler(signum, frame):
    """Handle Ctrl+C: first time shows warning, second time force quits"""
    global interrupt_count
    interrupt_count += 1

    if interrupt_count == 1:
        print("\n\n⚠ Shutdown requested. Press Ctrl+C again to force quit.")
        raise KeyboardInterrupt
    else:
        print("\n⚠ Force quitting...")
        os._exit(1)


def main():
    global rpc_server

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Try to connect to existing instance first
    print("Checking for existing instance...")
    client = RPCClient(port=18861)

    if client.connect():
        # Connected to existing instance, run as client
        try:
            client.run_interactive()
        except KeyboardInterrupt:
            print("\nDisconnecting...")
        finally:
            client.close()
        return

    # Initialize all components
    storage = Storage("data")
    config = storage.load_config()
    logger = Logger(config.logs_dir)
    cache = Cache(config.cache_dir)

    # Proxy configuration
    proxy_pool = None

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

    api = API(
        logger=logger,
        proxy_pool=proxy_pool
    )
    notifier = Notifier(
        enabled=False
    )
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
        max_workers=config.max_concurrent_artists
    )
    migrator = Migrator(
        storage=storage,
        cache=cache
    )
    validator = Validator(
        data_dir="data"
    )
    cli = CLI(
        storage=storage,
        scheduler=scheduler,
        logger=logger,
        cache=cache,
        api=api,
        downloader=downloader,
        migrator=migrator,
        validator=validator
    )
    rpc_server = RPCServer(cli.ctx, port=18861)

    try:
        rpc_server.start()
        scheduler.start()
        cli.run()
        logger.info(f"Started with {len(storage.get_artists())} artists")
    except KeyboardInterrupt:
        print("\nStopping all tasks...")
    finally:
        # Cleanup
        if rpc_server:
            rpc_server.stop()
        downloader.stop()
        scheduler.stop()
        proxy_pool.cleanup()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
