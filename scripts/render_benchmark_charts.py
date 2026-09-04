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
    ('GLM-5.3 (Flagship)', 'reports/benchmark_ark_glm-5.3_v1.0.json', '#818CF8'),       # Indigo
    ('DeepSeek-v4-pro', 'reports/benchmark_ark_deepseek-v4-pro_v1.0.json', '#34D399'),  # Emerald
    ('DeepSeek-v4-flash', 'reports/benchmark_ark_deepseek-v4-flash_v1.0.json', '#60A5FA'),# Sky Blue
    ('GLM-5.3-flash', 'reports/benchmark_ark_glm-5.3-flash_v1.0.json', '#FBBF24'),      # Amber
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
    })

# Sort descending by pass rate
data.sort(key=lambda x: x['overall'], reverse=False) # for horizontal bar, bottom to top

# ==========================================
# Chart: Benchmark Headline Pass@1 Leaderboard
# ==========================================
fig, ax = plt.subplots(figsize=(8.5, 3.8), dpi=300)
fig.patch.set_facecolor(fig_bg)
ax.set_facecolor(fig_bg)

y = np.arange(len(data))
height = 0.52

bars = ax.barh(y, [m['overall'] for m in data], height=height, 
               color=[m['color'] for m in data], edgecolor='none', zorder=3)

# Value annotations inside or outside the bar
for bar, m in zip(bars, data):
    w = bar.get_width()
    ax.text(w + 1.2, bar.get_y() + bar.get_height() / 2, 
            f"{w:.1f}%  ({m['passed']}/{m['total']})",
            va='center', ha='left', color=text_white, fontsize=10.5, fontweight='bold')

ax.set_yticks(y)
ax.set_yticklabels([m['name'] for m in data], color=text_white, fontsize=12, fontweight='bold')
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
