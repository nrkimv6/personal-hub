import sys

filepath = r'D:\work\project\service\wtools\common\tools\plan-runner\cli.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Add the engine option to the run function
old_run_sig = '''@app.command()
def run(
    plan_file: Optional[str] = typer.Option(None, "--plan-file", "-p", help="Plan ? 野以"),'''

new_run_sig = '''@app.command()
def run(
    engine: str = typer.Option("claude", "--engine", help="AI Engine to use"),
    plan_file: Optional[str] = typer.Option(None, "--plan-file", "-p", help="Plan ? 野以"),'''

if old_run_sig in content:
    content = content.replace(old_run_sig, new_run_sig)
    print("Run signature updated.")
else:
    print("Could not find run signature to update.")
    
# Update runner = Runner(config)
old_runner = '''    runner = Runner(config)'''
new_runner = '''    runner = Runner(config, engine=engine)'''

if old_runner in content:
    content = content.replace(old_runner, new_runner)
    print("Runner instantiation updated.")
else:
    print("Could not find Runner instantiation to update.")
    
# Update batch_runner = BatchRunner(config)
old_batch = '''        batch_runner = BatchRunner(config)'''
new_batch = '''        batch_runner = BatchRunner(config, engine=engine)'''
if old_batch in content:
    content = content.replace(old_batch, new_batch)
    print("BatchRunner instantiation updated.")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print("Done.")
