#!/usr/bin/env python3
"""Demonstrate the limits of cooperative shared-workspace evidence.

The simulated host records handles; no model or external service is launched.
A succeeds after its verifier writes B's file. B's host then reports success
without B writing. File hashes cannot identify the actual producer.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLI = ROOT / 'skills/workflow/scripts/workflow'


def probe(cli=DEFAULT_CLI):
    cli = Path(cli).resolve()
    with tempfile.TemporaryDirectory(prefix='weave-ownership-probe-') as tmp:
        base = Path(tmp); workspace = base/'workspace'; workspace.mkdir(); run = base/'run'
        definition = {'version':1,'name':'ownership-counterexample',
                      'goal':'Test whether evidence can prove which worker wrote a file',
                      'steps':[
                          {'id':'A','kind':'agent','needs':[],'prompt':'Write a.txt only',
                           'outputs':['a.txt'], 'verify':[[sys.executable,'-c',
                               "from pathlib import Path; Path('b.txt').write_text('written-by-A-verifier')"]]},
                          {'id':'B','kind':'agent','needs':[],'prompt':'Write b.txt only','outputs':['b.txt']}]}
        workflow = base/'workflow.json'; workflow.write_text(json.dumps(definition))
        trace=[]
        def call(*args):
            p=subprocess.run([sys.executable,str(cli),*map(str,args)],capture_output=True,text=True,timeout=15)
            packet=json.loads(p.stdout)
            trace.append({'operation':str(args[0]),'exit_code':p.returncode,'status':packet.get('status')})
            if p.returncode:raise RuntimeError(packet)
            return packet
        call('init','--workflow',workflow,'--repo',workspace,'--run-dir',run,
             '--max-active',2,'--shared-workspace-disjoint')
        claim=call('claim-ready','--run-dir',run,'--limit',2,'--request-id','both')
        actions={p['step_id']:p for p in claim['claimed_packets']}
        for step,packet in actions.items():
            call('prepare-dispatch','--run-dir',run,'--action',packet['action_id'])
            call('dispatch','--run-dir',run,'--action',packet['action_id'],'--handle','SIMULATED-'+step)
        (workspace/'a.txt').write_text('written-by-simulated-A')
        assert not (workspace/'b.txt').exists()
        for step in ['A','B']:
            result=base/f'{step}-result.json'
            result.write_text(json.dumps({'status':'succeeded','summary':'Simulated host success attestation'}))
            terminal=call('complete','--run-dir',run,'--action',actions[step]['action_id'],'--result',result)
        content=(workspace/'b.txt').read_text()
        return {'experiment':'shared-workspace-writer-identity',
                'assumption':'Disjoint declared paths and accepted receipts prove which native worker wrote each output.',
                'assumption_supported':False if terminal['status']=='complete' and content=='written-by-A-verifier' else None,
                'observation':{'workflow_status':terminal['status'],'b_contents':content,'b_worker_wrote_output':False},
                'disposition':'Cooperative ownership only. Do not claim sandboxing or writer provenance; evaluate isolated per-agent workspaces before stronger claims.',
                'native_handles':'simulated explicitly; no native agents launched',
                'cleanup':'temporary workspace and run removed after observation',
                'runtime_sha256':hashlib.sha256((cli.parent/'workflow_core.py').read_bytes()).hexdigest(),
                'trace':trace}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli',type=Path,default=DEFAULT_CLI)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    value=probe(args.cli)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'experiment':value['experiment'],'assumption_supported':value['assumption_supported'],
                      'output':str(args.output.resolve())}))


if __name__=='__main__':main()
