"""Rebuild report vector figures and analysis tables from archived measurements."""
import csv,json,statistics
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=Path(__file__).resolve().parents[1]
O=R/'report/assets';O.mkdir(exist_ok=True)
S=list(csv.DictReader((R/'experiments/multiposition/summary.csv').open()))
C=list(csv.DictReader((R/'experiments/multiposition/strong_scaling.csv').open()))
raw=[json.loads(l) for p in (R/'experiments/multiposition/raw').glob('*/runs.jsonl') for l in p.read_text().splitlines()]
names={'kiwipete':'Kiwipete','rook_endgame':'Rook/pawn','tactical':'Tactical','minor_endgame':'Minor pieces','ruy_lopez':'Ruy Lopez','queens_gambit':"Queen's Gambit"}
order=['kiwipete','rook_endgame','tactical','minor_endgame','ruy_lopez','queens_gambit']
colors=['#135a7a','#d06b32','#29917d','#8264a4','#b28224','#a44e68']
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'axes.labelcolor':'#253342','text.color':'#253342'})
def row(pos,backend,ranks,threads,split):
 return next(r for r in S if r['position']==pos and r['backend']==backend and int(r['ranks'])==ranks and int(r['threads'])==threads and int(r['split'])==split)
def time(r):return float(r['median_seconds'])

from matplotlib.colors import TwoSlopeNorm
from matplotlib.ticker import ScalarFormatter
# Global source checks: a chart is not allowed to silently change its denominator.
assert len(S)==120 and all(r['status']=='PASS' and int(r['trials'])==3 for r in S)
assert len(C)==24 and len({(r['position'],r['cores']) for r in C})==24
for p in order:
 for k in (1,2,3):
  matches=[r for r in raw if r['position']==p and r['phase']!='pilot' and r['exit_code']==0 and r.get('backend')=='mpi' and int(r['split_depth'])==k]
  assert len({r['nodes'] for r in matches})==1, (p,k,'nonconstant work')
fig,axs=plt.subplots(1,2,figsize=(8.2,4.1),layout='constrained')
for ax,positions,title,limits in [(axs[0],order[:4],'(a) Longer workloads',(.5,40)),(axs[1],order[4:],'(b) Shallow fallback workloads',(.06,1.25))]:
 for pos in positions:
  i=order.index(pos); data=sorted([r for r in C if r['position']==pos],key=lambda r:int(r['cores']))
  sr=row(pos,'serial',1,1,1); x=[int(r['cores']) for r in data];y=[float(r['speedup_vs_serial']) for r in data]
  low=[];high=[]
  for d,v in zip(data,y):
   pr=row(pos,'mpi',int(d['cores'])//72,72,3)
   low.append(v-float(sr['min_seconds'])/float(pr['max_seconds']))
   high.append(float(sr['max_seconds'])/float(pr['min_seconds'])-v)
  ax.errorbar(x,y,yerr=[low,high],label=names[pos],marker='o',capsize=3,color=colors[i],lw=1.8)
  ax.annotate(f'{y[-1]:.2f}x',(720,y[-1]),xytext=(5, {'kiwipete':-8,'tactical':8}.get(pos,0)),textcoords='offset points',fontsize=9,color=colors[i],va='center')
 ax.axhline(1,color='#444',ls='--',lw=1);ax.set_xscale('log',base=2);ax.set_yscale('log',base=2)
 ax.set_xlim(60,1100);ax.set_ylim(*limits);ax.set_xticks([72,144,288,720],labels=['72','144','288','720'])
 ticks=[.5,1,2,4,8,16,32] if ax is axs[0] else [.0625,.125,.25,.5,1]
 ax.set_yticks(ticks,labels=[f'{v:g}x' for v in ticks]);ax.set_title(title,loc='left',fontsize=11,fontweight='bold')
 ax.set_xlabel('Allocated CPU cores');ax.set_ylabel('Serial time / parallel search time');ax.grid(axis='y',alpha=.18);ax.legend(fontsize=9,loc='upper left' if ax is axs[0] else 'upper right')
fig.savefig(O/'scaling.pdf');plt.close(fig)
fig,ax=plt.subplots(figsize=(8.2,3.6),layout='constrained')
positions=['initial']+order
for y,pos in enumerate(positions):
 if pos=='initial':a,b=5.34012/1.75406,198.129/1.75406;label='Initial position (d8)'
 else:
  r=next(r for r in C if r['position']==pos and r['cores']=='720');a=float(r['speedup_vs_serial']);b=float(r['speedup_vs_task']);label=names[pos]+f" (d{r['depth']})"
 ax.plot([a,b],[y,y],color='#a9b5bf',lw=2)
 ax.scatter(a,y,color='#135a7a',s=40,label='vs serial alpha-beta' if y==0 else None,zorder=3)
 ax.scatter(b,y,color='#d06b32',s=40,marker='s',label='vs same task algorithm, 1 worker' if y==0 else None,zorder=3)
 ax.annotate(f'{a:.2f}x',(a,y),xytext=(-6,0),textcoords='offset points',ha='right',va='center',fontsize=9,color='#135a7a')
 ax.annotate(f'{b:.1f}x',(b,y),xytext=(6,0),textcoords='offset points',va='center',fontsize=9,color='#a74d21')
ax.set_yticks(range(7),labels=['Initial position (d8)']+[names[p]+f" (d{next(r['depth'] for r in C if r['position']==p)})" for p in order]);ax.invert_yaxis();ax.set_xscale('log');ax.set_xlim(.035,1000);ax.set_xticks([.1,1,10,100,1000],labels=['0.1x','1x','10x','100x','1000x']);ax.axvline(1,ls='--',color='#666',lw=1);ax.set_xlabel('720-core speedup: same parallel time, different reference');ax.legend(loc='lower right',fontsize=9);ax.grid(axis='x',alpha=.15)
fig.savefig(O/'baselines.pdf');plt.close(fig)
A=[]
for pos in order:
 ns=int(next(r for r in raw if r['position']==pos and r['phase']!='pilot' and r.get('backend')=='serial' and r['exit_code']==0)['nodes'])
 A.append([int(next(r for r in raw if r['position']==pos and r['phase']!='pilot' and r.get('backend')=='mpi' and r['threads']=='1' and int(r['split_depth'])==k and r['exit_code']==0)['nodes'])/ns for k in (1,2,3)])
fig,ax=plt.subplots(figsize=(8.2,3.2),layout='constrained'); x=np.arange(6)
for k,c in enumerate(['#95b7c7','#4587a5','#123f59']):
 bars=ax.bar(x+(k-1)*.25,np.array(A)[:,k],width=.23,color=c,label=f'Split depth {k+1}')
 if k==2:
  for bar,v in zip(bars,np.array(A)[:,k]):ax.text(bar.get_x()+bar.get_width()/2,v+.7,f'{v:.1f}x',ha='center',fontsize=9)
ax.set_xticks(x,labels=[names[p].replace(' ','\n') for p in order]);ax.set_ylabel('Logical node visits / serial node visits');ax.set_ylim(0,46);ax.legend(ncol=3,fontsize=9,loc='upper left');ax.grid(axis='y',alpha=.18)
fig.savefig(O/'work.pdf');plt.close(fig)
fig,ax=plt.subplots(figsize=(8.2,3.5),layout='constrained')
M=np.array([[time(row(p,'mpi',4,4,k))/time(row(p,'serial',1,1,1)) for k in (1,2,3)]+[time(row(p,'mpi-pv',4,4,1))/time(row(p,'serial',1,1,1))] for p in order])
im=ax.imshow(np.log2(M),cmap='RdBu_r',norm=TwoSlopeNorm(vmin=-3,vcenter=0,vmax=4),aspect='auto')
for i in range(6):
 for j in range(4):ax.text(j,i,f'{M[i,j]:.2f}x',ha='center',va='center',fontsize=11,fontweight='bold',color='white' if abs(np.log2(M[i,j]))>1.5 else '#182d3b')
ax.set_xticks(range(4),labels=['Root split','Split depth 2','Split depth 3','Seeded root']);ax.set_yticks(range(6),labels=[names[p] for p in order]);ax.set_title('16-core time / serial time: below 1 = faster; above 1 = slower',loc='left',fontsize=11,pad=12)
cbar=fig.colorbar(im,ax=ax,shrink=.9,pad=.03);cbar.set_ticks([-3,-2,-1,0,1,2,3,4],labels=['0.125','0.25','0.5','1','2','4','8','16']);cbar.set_label('Runtime ratio')
from matplotlib.ticker import NullLocator
cbar.ax.yaxis.set_minor_locator(NullLocator())
fig.savefig(O/'strategy.pdf');plt.close(fig)
# Derive phases from the actual depth-eight explicit-copy log, not rounded prose.
import re
log=R/'experiments/raw/1518578-gpu-profile.txt'
gpu=next(dict(re.findall(r'(\w+)=([^\s]+)',line)) for line in log.read_text().splitlines() if line.startswith('backend=gpu-chunk-profile depth=8'))
total=float(gpu['seconds']);build=float(gpu['preparation_seconds']);target=float(gpu['kernel_region_seconds']);copies=float(gpu['h2d_seconds'])+float(gpu['d2h_seconds']);other=total-build-target-copies
fig,ax=plt.subplots(figsize=(8.2,2.8),layout='constrained');left=0
for name,v,c in [('CPU tree generation',build,'#d06b32'),('Target launch + search',target,'#135a7a'),('Explicit H2D + D2H',copies,'#29917d'),('Probe + allocation + other',other,'#bfc8d0')]:
 ax.barh(0,v,left=left,color=c,height=.5,label=f'{name}: {v:.2f} s ({100*v/total:.1f}%)')
 if v>20:ax.text(left+v/2,0,f'{100*v/total:.1f}%',ha='center',va='center',color='white',fontweight='bold',fontsize=12)
 left+=v
ax.set_xlim(0,total);ax.set_ylim(-.65,.6);ax.set_yticks([]);ax.set_xlabel('End-to-end GPU pipeline time (seconds)');ax.set_title('One A40 depth-8 profile: 154.62 s total',loc='left',fontsize=12,fontweight='bold');ax.legend(loc='upper center',bbox_to_anchor=(.5,-.32),ncol=2,fontsize=9,frameon=False);ax.grid(axis='x',alpha=.15);ax.spines['left'].set_visible(False)
fig.savefig(O/'gpu_phases.pdf',bbox_inches='tight');plt.close(fig)
with (O/'scaling_rows.tex').open('w') as f:
 for p in order:
  d=sorted([r for r in C if r['position']==p],key=lambda r:int(r['cores'])); z=d[-1];H=float(z['task_one_worker_seconds'])/float(z['serial_seconds'])
  times=' & '.join(f"{float(r['seconds']):.3f}" for r in d)
  f.write(f"{names[p]} & {z['depth']} & {float(z['serial_seconds']):.3f} & {times} & {float(z['speedup_vs_serial']):.2f} & {100*float(z['efficiency_vs_task']):.1f}\\\\\n")
with (O/'work_rows.tex').open('w') as f:
 for p,a in zip(order,A):
  r=next(x for x in C if x['position']==p);H=float(r['task_one_worker_seconds'])/float(r['serial_seconds']); n=int(next(x for x in raw if x['position']==p and x['phase']!='pilot' and x.get('backend')=='serial' and x['exit_code']==0)['nodes'])
  f.write(f"{names[p]} & {n/1e6:.3f} & {a[0]:.2f} & {a[1]:.2f} & {a[2]:.2f} & {H:.2f}\\\\\n")
with (O/'strategy_rows.tex').open('w') as f:
 for p in order:
  vals=[time(row(p,'mpi',4,4,k)) for k in (1,2,3)]+[time(row(p,'mpi-pv',4,4,1))];best=min(range(4),key=lambda i:vals[i]);fmt=[f'{v:.4f}' for v in vals];fmt[best]='\\textbf{'+fmt[best]+'}'
  f.write(names[p]+' & '+' & '.join(fmt)+'\\\\\n')
print('Generated five vector figures and four evidence tables')

# Keep the report's embedded tables synchronized without TeX input alignment issues.
import re
p=R/'report/main.tex'
text=p.read_text()
for name in ('scaling','work','strategy'):
 pattern=r'% BEGIN GENERATED '+name+r'\n.*?% END GENERATED '+name
 replacement='% BEGIN GENERATED '+name+'\n'+(O/(name+'_rows.tex')).read_text()+'% END GENERATED '+name
 text=re.sub(pattern,lambda m:replacement,text,flags=re.S)
p.write_text(text)
# Launcher-inclusive comparison uses the same successful formal archive records.
with (O/'scope_rows.tex').open('w') as f:
 for pos in order:
  records=[r for r in raw if r['position']==pos and r['phase']!='pilot' and r['exit_code']==0]
  a=[float(r['launch_seconds']) for r in records if r.get('backend')=='serial']
  b=[float(r['launch_seconds']) for r in records if r.get('backend')=='mpi' and r['ranks']=='10' and r['threads']=='72']
  r=next(r for r in C if r['position']==pos and r['cores']=='720')
  f.write(f"{names[pos]} & {statistics.median(a):.3f} & {statistics.median(b):.3f} & {float(r['speedup_vs_serial']):.2f} & {statistics.median(a)/statistics.median(b):.2f}\\\\\n")
p=R/'report/main.tex';text=p.read_text()
replacement='% BEGIN GENERATED scope\n'+(O/'scope_rows.tex').read_text()+'% END GENERATED scope'
text=re.sub(r'% BEGIN GENERATED scope\n.*?% END GENERATED scope',lambda m:replacement,text,flags=re.S)
p.write_text(text)
