"""Private single-GPU backend lifecycle for bounded independent probes."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import aiohttp


def save(path, data):
    with Path(path).open('x') as stream:
        json.dump(data, stream, indent=2)


def check_private_port(port):
    # Match the server's normal address reuse: a closed owned connection may
    # leave TIME_WAIT. Never enable SO_REUSEPORT; a live listener must still fail.
    # This remains an advisory preflight, not a reservation against bind races.
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', port))


class OwnedBackend:
    def __init__(self, args):
        self.args = args
        self.process = None
        self.log = None
        self.url = f'http://127.0.0.1:{args.port}'

    async def __aenter__(self):
        args = self.args
        if os.name != 'posix' or not args.vllm.is_file() or not (args.model/'config.json').is_file():
            raise ValueError('Linux, existing executable and model required')
        if subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'], text=True).strip():
            raise RuntimeError('GPU busy')
        check_private_port(args.port)
        args.output.mkdir(parents=True, exist_ok=False)
        command = [str(args.vllm), 'serve', str(args.model), '--host', '127.0.0.1', '--port', str(args.port),
                   '--served-model-name', getattr(args, 'served_model_name', 'cancel-probe'), '--dtype', 'float16', '--max-model-len', '4096',
                   '--gpu-memory-utilization', '.75', '--disable-uvicorn-access-log', '--no-enable-prefix-caching',
                   '--enable-chunked-prefill', '--max-num-batched-tokens', '1024', '--max-num-seqs', '256',
                   '--scheduling-policy', 'fcfs']
        if getattr(args, 'request_logs', False):
            command += ['--enable-log-requests']
        save(args.output/'manifest.json', dict(command=command,
             sources={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
             model_config_sha256=hashlib.sha256((args.model/'config.json').read_bytes()).hexdigest(),
             gpu=subprocess.check_output(['nvidia-smi'], text=True)))
        self.log = (args.output/'backend.log').open('x')
        try:
            self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
            save(args.output/'owned_process.json', dict(pid=self.process.pid, pgid=self.process.pid))
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
                deadline = time.monotonic()+240
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise RuntimeError('backend exited during startup')
                    try:
                        async with session.get(self.url+'/health') as response:
                            if response.status == 200:
                                return self
                    except (aiohttp.ClientError, TimeoutError):
                        pass
                    await asyncio.sleep(1)
                raise TimeoutError('startup deadline')
        except BaseException:
            await self.close()
            raise

    async def close(self):
        result = dict(stopped=True)
        if self.process:
            pid = self.process.pid
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(asyncio.to_thread(self.process.wait), 20)
            except TimeoutError:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await asyncio.to_thread(self.process.wait)
            await asyncio.sleep(2)
            try:
                os.killpg(pid, 0)
            except ProcessLookupError:
                pass
            else:
                os.killpg(pid, signal.SIGKILL)
                await asyncio.sleep(2)
                try:
                    os.killpg(pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    result['stopped'] = False
            result['exit_code'] = self.process.returncode
        if self.log:
            self.log.close()
        save(self.args.output/'cleanup.json', result)

    async def __aexit__(self, *_):
        await self.close()
