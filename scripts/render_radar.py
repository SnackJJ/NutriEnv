import glob
import json
import numpy as np
import matplotlib.pyplot as plt

models = [
    ('DeepSeek-v4-pro', 'reports/benchmark_commandcode_deepseek-v4-pro_v1.0_fc_r*.json', '#34D399'),  # Emerald
    ('GLM-5.3-flash', 'reports/benchmark_commandcode_glm-5.3-flash_v1.0_fc_r*.json', '#FBBF24'),      # Amber
    ('MiMo-v2.6-flash', 'reports/benchmark_commandcode_mimo-v2.6-flash_v1.0_fc_r*.json', '#F472B6'),  # Pink
    ('DeepSeek-v4-flash', 'reports/benchmark_commandcode_deepseek-v4-flash_v1.0_fc_r*.json', '#60A5FA'),# Sky Blue
    ('DeepSeek-v4.1-flash', 'reports/benchmark_commandcode_deepseek-v4.1-flash_v1.0_fc_r*.json', '#818CF8'),  # Indigo
]

categories = [
    'Update\n(User Profile)', 
    'Log\n(Portion Grounding)', 
    'Evaluate\n(Safety & Myths)', 
    'Recommend\n(Nutrient Planning)', 
    'Composite\n(Multi-step Long Chain)'
]
num_vars = len(categories)

angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
angles += angles[:1]

fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True), dpi=300)
fig.patch.set_facecolor('#090D16')
ax.set_facecolor('#090D16')

ax.set_theta_offset(np.pi / 2)
ax.set_theta_direction(-1)

# Axis ticks & styling
plt.xticks(angles[:-1], categories, color='#F1F5F9', size=13, weight=600)
ax.tick_params(axis='x', pad=25)

ax.set_rscale('linear')
plt.yticks([20, 40, 60, 80, 100], ["20%", "40%", "60%", "80%", "100%"], color='#64748B', size=9)
plt.ylim(0, 105)

ax.spines['polar'].set_color('#1E293B')
ax.xaxis.grid(True, color='#1E293B', linestyle='--', linewidth=1.2)
ax.yaxis.grid(True, color='#1E293B', linestyle='-', linewidth=0.8)

for name, pattern, color in models:
    # Pooled over the model's complete runs (one report per run).
    runs = [json.load(open(p)) for p in sorted(glob.glob(pattern))]
    families = ['update', 'log', 'evaluate', 'recommend', 'composite']
    vals = [
        100.0 * sum(d['family_breakdown'][f]['passed'] for d in runs)
        / sum(d['family_breakdown'][f]['total'] for d in runs)
        for f in families
    ]
    vals += vals[:1]
    
    overall = 100.0 * sum(d['passed_tasks'] for d in runs) / sum(d['total_tasks'] for d in runs)
    label = f"{name:19s} {overall:4.1f}%"
    
    ax.plot(angles, vals, color=color, linewidth=2.5, linestyle='solid', label=label)
    ax.fill(angles, vals, color=color, alpha=0.12)
    ax.scatter(angles[:-1], vals[:-1], color=color, s=50, zorder=10)

legend = plt.legend(
    loc='upper right',
    bbox_to_anchor=(1.32, 1.12),
    frameon=True,
    facecolor='#0F172A',
    edgecolor='#334155',
    fontsize=11,
    prop={'family': 'monospace', 'weight': 'bold', 'size': 10.5},
    labelcolor='#F8FAFC'
)

plt.title("NutriEnv v1.0 Benchmark Radar\nDomain Grounding & Interactive State Planning", 
          size=16, color='#FFFFFF', weight='bold', pad=38)

plt.tight_layout()
plt.savefig('reports/assets/radar_v1.0_family.png', bbox_inches='tight', facecolor=fig.get_facecolor())
print('Updated radar chart saved.')
