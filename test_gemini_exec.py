import asyncio
import sys

async def test_gemini_exec():
    cmd = 'gemini.cmd' if sys.platform == 'win32' else 'gemini'
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd, '--help',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            print("SUCCESS: gemini CLI found and executed.")
        else:
            print(f"FAILED: gemini CLI returned code {proc.returncode}")
            print(stderr.decode('utf-8', errors='replace'))
    except FileNotFoundError as e:
        print(f"FATAL ERROR: Could not find executable: {e}")

asyncio.run(test_gemini_exec())
