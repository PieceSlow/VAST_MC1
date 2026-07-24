
# Visualization source

后续所有可复现绘图代码统一放在本目录。建议文件名：

```text
plot_q1_timeline.py
plot_q1_actor_sequence.py
plot_q1_control_bypass.py
plot_q2_behavior_comparison.py
plot_q3_leading_indicators.py
plot_q3_expected_vs_actual.py
```

每个脚本应：

- 从 `data/cleaned/` 或 `data/features/` 读取数据；
- 把结果写入对应的 `outputs/figures/q*/`；
- 在脚本顶部说明输入、输出和运行命令；
- 不依赖绝对路径；
- 保留图中事件与原始消息证据之间的可追溯关系。

当前压缩包只有图形成果，没有完整制图脚本，因此本目录暂时只保留这份说明。
