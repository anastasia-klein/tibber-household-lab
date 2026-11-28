"""Optional private hourly consumption box plots; no household assets are published."""
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from .analysis import instant
from .patterns import describe_consumption


def render_hourly_boxplots(consumption,zone_name,start,end,output):
    # Validate interval coverage; the caller selects the research period and its provenance.
    summary=describe_consumption(consumption,zone_name,start,end)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    zone=ZoneInfo(zone_name);groups=defaultdict(list)
    for row in consumption:
        t=instant(row['from'])
        if start<=t<end:
            local=t.astimezone(zone)
            groups[(local.weekday()>=5,local.hour)].append(row['consumption'])
    colors=['#397de0','#16a092']
    fig,ax=plt.subplots(figsize=(16,7),layout='constrained')
    fig.patch.set_facecolor('#f5f8fc')
    for weekend,color in zip((False,True),colors):
        values=[groups[(weekend,h)] for h in range(24)]
        # Empty physical-hour groups remain empty, rather than being filled with zero.
        offset=.19 if weekend else -.19
        ax.boxplot(values,positions=[h+offset for h in range(24)],widths=.32,manage_ticks=False,whis=1.5,patch_artist=True,showmeans=True,
            boxprops={'facecolor':color,'alpha':.25,'edgecolor':color,'linewidth':1.3},
            medianprops={'color':'#20334c','linewidth':1.7},
            whiskerprops={'color':color,'linewidth':1},capprops={'color':color,'linewidth':1},
            flierprops={'marker':'o','markersize':2.7,'markerfacecolor':color,'markeredgecolor':'none','alpha':.42},
            meanprops={'marker':'D','markersize':3.5,'markerfacecolor':'#efaa31','markeredgecolor':'#b87d11','markeredgewidth':.4})
        ax.set_facecolor('white');ax.spines[['top','right']].set_visible(False)
        ax.grid(axis='y',color='#e4eaf3');ax.set_axisbelow(True)
        ax.set_ylabel('Consumption (kWh per hour)',fontsize=11,color='#20334c')
        ax.set_xticks(range(24),[f'{h:02}' for h in range(24)]);ax.tick_params(axis='x',labelbottom=True)
        ax.set_xlim(-.8,23.8)
    maximum=max(q for v in groups.values() for q in v)
    ax.set_ylim(0,maximum*1.08 if maximum else 1)
    ax.set_xlabel(f'Local clock hour - {zone_name}',fontsize=11)
    last_date=end.astimezone(zone).date()-timedelta(days=1)
    fig.suptitle(f"Hourly consumption distributions, {start.astimezone(zone):%d %b} - {last_date:%d %b %Y}",fontsize=16,weight='bold',color='#20334c')
    ax.legend(handles=[Patch(facecolor=colors[0],alpha=.45,label=f"Weekdays ({summary['daytypes']['weekday']['days']} days)"),
        Patch(facecolor=colors[1],alpha=.45,label=f"Weekends ({summary['daytypes']['weekend']['days']} days)"),Line2D([0],[0],color='#20334c',lw=1.7,label='Median'),
        Line2D([0],[0],marker='D',ls='',color='#efaa31',markersize=5,label='Mean')],frameon=False,loc='upper right',ncol=4)
    counts=[f"{'Weekend' if w else 'Weekday'} hourly n={min(len(groups[(w,h)]) for h in range(24))}-{max(len(groups[(w,h)]) for h in range(24))}" for w in (False,True)]
    fig.supxlabel('Box: middle 50% (Q1-Q3). Whiskers: observations within 1.5 x IQR. Dots: observations beyond whiskers.\n'+ '; '.join(counts)+'. Paired boxes: weekdays left, weekends right; all outliers retained.',fontsize=10,color='#647690')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fig.savefig(output,dpi=160);output.chmod(0o600);plt.close(fig)
    return {f"{'weekend' if w else 'weekday'}":{str(h):len(groups[(w,h)]) for h in range(24)} for w in (False,True)}


def main():
    import argparse
    from datetime import datetime,date
    from . import storage
    parser=argparse.ArgumentParser(description='Private hourly weekday/weekend box plots')
    parser.add_argument('--start',required=True);parser.add_argument('--end',required=True,help='Exclusive local date')
    parser.add_argument('--output-dir',help='Private output directory outside Git; defaults to runtime storage')
    args=parser.parse_args();conf=storage.config();zone=ZoneInfo(conf.get('timezone','Europe/Berlin'))
    start=datetime.combine(date.fromisoformat(args.start),datetime.min.time(),zone)
    end=datetime.combine(date.fromisoformat(args.end),datetime.min.time(),zone)
    with storage.connect() as db:rows=storage.read_rows(db,'consumption')
    directory=Path(args.output_dir) if args.output_dir else storage.data_dir()
    render_hourly_boxplots(rows,zone.key,start,end,directory/'hourly_boxplots.png')
    print('Private weekday/weekend hourly box plots saved. No household data published.')


if __name__=='__main__':main()
