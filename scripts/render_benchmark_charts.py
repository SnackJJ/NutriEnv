import json
import matplotlib.pyplot as plt
import numpy as np

plt.style.use('dark_background')
fig_bg = '#090D16'
panel_bg = '#0F172A'
grid_color = '#1E293B'
text_white = '#F8FAFC'
text_muted = '#94A3B8'

models = [
    ('GLM-5.3 (Flagship)', 'reports/benchmark_ark_glm-5.3_v1.0.json', '#818CF8'),              # Indigo
    ('DeepSeek-v4-pro', 'reports/benchmark_ark_deepseek-v4-pro_v1.0.json', '#34D399'),         # Emerald
    ('DeepSeek-v4-flash', 'reports/benchmark_ark_deepseek-v4-flash_v1.0.json', '#60A5FA'),       # Sky Blue
    ('GLM-5.3-flash', 'reports/benchmark_ark_glm-5.3-flash_v1.0.json', '#FBBF24'),             # Amber
]

data = []
for name, p, color in models:
    d = json.load(open(p))
    data.append({
        'name': name,
        'color': color,
        'overall': d['pass_rate_pct'],
        'passed': d['passed_tasks'],
        'total': d['total_tasks'],
        'latency': d['overall_avg_time_seconds'],
        'tokens_k': d['overall_avg_tokens_per_task'] / 1000.0,
        'total_tokens': d['overall_total_tokens'],
        'avg_steps': d['overall_avg_steps'],
    })

# ==========================================
# Chart 1: Benchmark Headline Pass@1 Leaderboard
# ==========================================
bar_data = sorted(data, key=lambda x: x['overall'], reverse=False) # bottom to top

fig, ax = plt.subplots(figsize=(8.5, 3.8), dpi=300)
fig.patch.set_facecolor(fig_bg)
ax.set_facecolor(fig_bg)

y = np.arange(len(bar_data))
height = 0.52

bars = ax.barh(y, [m['overall'] for m in bar_data], height=height, 
               color=[m['color'] for m in bar_data], edgecolor='none', zorder=3)

# Value annotations inside or outside the bar
for bar, m in zip(bars, bar_data):
    w = bar.get_width()
    ax.text(w + 1.2, bar.get_y() + bar.get_height() / 2, 
            f"{w:.1f}%  ({m['passed']}/{m['total']})",
            va='center', ha='left', color=text_white, fontsize=10.5, fontweight='bold')

ax.set_yticks(y)
ax.set_yticklabels([m['name'] for m in bar_data], color=text_white, fontsize=12, fontweight='bold')
ax.set_xlim(0, 85)
ax.set_xlabel('Benchmark Pass Rate (%)  [63 Tasks]', color=text_muted, fontsize=10.5, labelpad=8)

ax.xaxis.grid(True, color=grid_color, linestyle='--', linewidth=0.8, zorder=0)
ax.yaxis.grid(False)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.spines['left'].set_color(grid_color)
ax.spines['bottom'].set_color(grid_color)
ax.tick_params(axis='x', colors=text_muted)
ax.tick_params(axis='y', colors=text_white, length=0)

plt.title('NutriEnv v1.0 Overall Benchmark Leaderboard (Pass@1)', 
          color=text_white, fontsize=13.5, fontweight='bold', pad=16, loc='left')
plt.tight_layout()
plt.savefig('reports/assets/eval_leaderboard_bars.png', facecolor=fig_bg)
plt.close()
print('Pure model leaderboard bar chart saved to reports/assets/eval_leaderboard_bars.png')

# ==========================================
# Chart 2: Pareto Efficiency Frontier (Tokens vs Pass Rate)
# ==========================================
fig, ax = plt.subplots(figsize=(9.0, 5.0), dpi=300)
fig.patch.set_facecolor(fig_bg)
ax.set_facecolor(fig_bg)

# Scatter plot each model
for m in data:
    ax.scatter(m['tokens_k'], m['overall'], color=m['color'], s=140, zorder=5, edgecolors='white', linewidth=1.5)

# Label positions customized to avoid overlapping cleanly
offsets = {
    'DeepSeek-v4-flash': (12, 4, 'left'),
    'GLM-5.3-flash': (12, -12, 'left'),
    'DeepSeek-v4-pro': (0, 14, 'center'),
    'GLM-5.3 (Flagship)': (0, 14, 'center'),
}

for m in data:
    cfg = offsets.get(m['name'], (10, 5, 'left'))
    dx, dy, ha = cfg[0], cfg[1], cfg[2]
    ax.annotate(
        f"{m['name']}\n({m['overall']:.1f}%, {m['tokens_k']:.1f}k)",
        (m['tokens_k'], m['overall']),
        textcoords="offset points",
        xytext=(dx, dy),
        ha=ha,
        fontsize=9.5,
        color=text_white,
        fontweight='bold',
        zorder=6
    )

# Compute Pareto Frontier (lower tokens is better [X min], higher pass rate is better [Y max])
sorted_by_tokens = sorted(data, key=lambda x: x['tokens_k'])
pareto_points = []
cur_max_pass = -1.0
for m in sorted_by_tokens:
    if m['overall'] > cur_max_pass:
        pareto_points.append(m)
        cur_max_pass = m['overall']

px = [p['tokens_k'] for p in pareto_points]
py = [p['overall'] for p in pareto_points]

ax.plot(px, py, color='#38BDF8', linestyle='--', linewidth=1.8, alpha=0.85, zorder=4, label='Pareto Frontier')

ax.set_xlim(25, 95)
ax.set_ylim(55, 80)
ax.set_xlabel('Average Tokens per Task (k tokens)', color=text_muted, fontsize=11, labelpad=10)
ax.set_ylabel('Benchmark Pass Rate (%)  [63 Tasks]', color=text_muted, fontsize=11, labelpad=10)

ax.xaxis.grid(True, color=grid_color, linestyle='--', linewidth=0.8, zorder=0)
ax.yaxis.grid(True, color=grid_color, linestyle='--', linewidth=0.8, zorder=0)

ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.spines['left'].set_color(grid_color)
ax.spines['bottom'].set_color(grid_color)
ax.tick_params(axis='x', colors=text_muted)
ax.tick_params(axis='y', colors=text_muted)

# Annotation for top-left ideal direction
ax.annotate('Ideal Region (High Accuracy, Low Tokens)', 
            xy=(0.04, 0.94), xycoords='axes fraction',
            color='#38BDF8', fontsize=9.5, fontweight='bold',
            bbox=dict(boxstyle="round,pad=0.35", fc=panel_bg, ec='#38BDF8', lw=1.2, alpha=0.9))

ax.set_ylim(20, 88)

plt.title('NutriEnv v1.0 Pareto Efficiency (Token Cost vs. Accuracy)', 
          color=text_white, fontsize=13.5, fontweight='bold', pad=16, loc='left')
plt.legend(loc='lower right', facecolor=panel_bg, edgecolor=grid_color, fontsize=10)
plt.tight_layout()
plt.savefig('reports/assets/eval_pareto_efficiency.png', facecolor=fig_bg)
plt.close()
print('Pareto efficiency chart saved to reports/assets/eval_pareto_efficiency.png')

