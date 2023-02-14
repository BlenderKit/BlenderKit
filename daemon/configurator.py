import asyncio
import os
import socket
import ssl
from logging import getLogger

import aiohttp
import certifi
from aiohttp import web


logger = getLogger(__name__)

URL = "https://www.blenderkit.com/-/alive/"
CA_FILE = os.path.join(os.path.dirname( __file__ ), "certs/blenderkit-com-chain.pem")


async def debug_handler(request: web.Request):
    logger.info(CA_FILE)
    results = await debug_connection()
    text = f"Results for connection to {URL} are:\n\n"
    for configuration, result in results.items():
        text += f"{configuration}: {result}\n"
    
    return web.Response(text=text)

async def debug_and_print():
    results = await debug_connection()
    for configuration, result in results.items():
        print(f"{configuration}: {result}")

async def debug_connection():
    connectors = await get_connectors()
    logger.info(f'connectors: {len(connectors)}')

    sessions = await get_sessions(connectors)
    logger.info(f'sessions: {len(sessions)}')
    results = {}
    for key, session in sessions.items():
        try:
            async with session.get(URL) as resp:
                results[key] = resp.status
        except Exception as e:
            results[key] = str(e)

    for key, session in sessions.items():
        await session.close()
        
    return results


async def get_sessions(connectors):
    sessions = {}
    trust_envs = {
        'trust_env=False': False,
        'trust_env=True': True,
    }
    for connector in connectors:
        for trust_env in trust_envs:
            key = f"{connector} + {trust_env}"
            session = aiohttp.ClientSession(
                connector=connectors[connector],
                trust_env=trust_envs[trust_env],
                raise_for_status=True,
                )
            sessions[key] = session
    return sessions


async def get_connectors():
    use_dns_caches = {
        'use_dns_cache=True': True,
        'use_dns_cache=False': False,
    }
    families = {
        'IPv4 & IPv6': 0,
        'IPv4': socket.AF_INET,
        'IPv6': socket.AF_INET6,
    }
    ssl_contexts = {
        context1.__doc__: await context1(),
        context2.__doc__: await context2(),
        context3.__doc__: await context3(),
        context4.__doc__: await context4(),
        context5.__doc__: await context5(),
        context6.__doc__: await context6(),
        context7.__doc__: await context7(),
        context8.__doc__: await context8(),
        context9.__doc__: await context9(),
        context10.__doc__: await context10(),
        context11.__doc__: await context11(),
        context12.__doc__: await context12(),
        context13.__doc__: await context13(),
        context14.__doc__: await context14(),
        context15.__doc__: await context15(),
        context16.__doc__: await context16(),
        context17.__doc__: await context17(),
        context18.__doc__: await context18(),
        context19.__doc__: await context19(),
    }
    connections = {}
    for ssl_context in ssl_contexts:
        for family in families:
            for use_dns_cache in use_dns_caches:
                key = f"{ssl_context} @ {family} + {use_dns_cache}"
                connector = aiohttp.TCPConnector(
                    ssl=ssl_contexts[ssl_context],
                    family=families[family],
                    use_dns_cache=use_dns_caches[use_dns_cache],
                    )
                connections[key] = connector

    return connections


async def context1():
    """default context"""
    ssl_context = ssl.create_default_context()
    return ssl_context

async def context2():
    """default context + certifi"""
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(certifi.where())
    return ssl_context

async def context3():
    """default context + certifi + default certs"""
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    return ssl_context

async def context4():
    """default context + certifi + default certs + set_default_verify_paths"""
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    ssl_context.set_default_verify_paths()
    return ssl_context

async def context5():
    """default context + blenderkit-com-chain.pem"""
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(cafile=CA_FILE)
    return ssl_context

async def context6():
    """default context + default certs + blenderkit-com-chain.pem"""
    ssl_context = ssl.create_default_context()
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_verify_locations(cafile=CA_FILE)
    return ssl_context

async def context7():
    """default context + certifi + blenderkit-com-chain.pem"""
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.load_verify_locations(cafile=CA_FILE)
    return ssl_context  

async def context8():
    """default context + certifi + default certs + blenderkit-com-chain.pem"""
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_verify_locations(cafile=CA_FILE)
    return ssl_context  

async def context9():
    """default context + certifi + default certs + set_default_verify_paths + blenderkit-com-chain.pem"""
    ssl_context = ssl.create_default_context()
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    ssl_context.set_default_verify_paths()
    ssl_context.load_verify_locations(cafile=CA_FILE)
    return ssl_context

async def context10():
    """SSLContext + certifi"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_verify_locations(certifi.where())
    return ssl_context

async def context11():
    """SSLContext + default certs"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    return ssl_context

async def context12():
    """SSLContext + certifi + default certs"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    return ssl_context

async def context13():
    """SSLContext + certifi + default certs + set_default_verify_paths"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    ssl_context.set_default_verify_paths()
    return ssl_context

async def context14():
    """SSLContext + blenderkit-com-chain.pem"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_verify_locations(cafile=CA_FILE)
    return ssl_context

async def context15():
    """SSLContext + certifi + blenderkit-com-chain.pem"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.load_verify_locations(cafile=CA_FILE)
    return ssl_context

async def context16():
    """SSLContext + default certs + blenderkit-com-chain.pem"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_verify_locations(cafile=CA_FILE)
    return ssl_context

async def context17():
    """SSLContext + certifi + default certs + blenderkit-com-chain.pem"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_verify_locations(cafile=CA_FILE)
    return ssl_context

async def context18():
    """SSLContext + certifi + default certs + set_default_verify_paths + blenderkit-com-chain.pem"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.load_verify_locations(certifi.where())
    ssl_context.load_default_certs(purpose=ssl.Purpose.CLIENT_AUTH)
    ssl_context.set_default_verify_paths()
    ssl_context.load_verify_locations(cafile=CA_FILE)
    return ssl_context

async def context19():
    """SSLContext"""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return ssl_context


if __name__ == '__main__':
    asyncio.run(debug_and_print())

