# MySubstanceDesigner / Material Lab Qt

本地节点材质编辑实验，当前版本 **0.12**。使用 Python、PySide6、OpenGL 与 NumPy。

## 启动

需要 Python 3.10+、支持 OpenGL 3.3 的显卡。主要开发和验证平台为 Windows。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

Windows 也可以双击 `启动Qt.cmd`，首次运行会创建环境并安装依赖。

## 当前功能

- Qt 主窗口、停靠面板、节点连线、参数编辑、撤销重做、2D/3D 预览。
- 独立 JSON 程序纹理工程与 GLSL 节点计算。
- 从文件菜单打开 SBS，在原窗口左侧 Package 下选择图表编辑，保存为 `.mlsbs`。
- SBS 的 CPU float32 求值子集：混合、色阶、变换、灰度、Pixel Processor、模糊、位移、法线、HSL、通道重排与渐变。
- 25 种可添加的 SBS 包装节点，执行本机安装库中的实际图定义。
- 渐变关键点列表编辑、参数函数子集、手动 Mipmap。

## 兼容边界

这是独立实验实现，不是 Adobe 产品，也不包含 Adobe 渲染引擎。空间滤镜等为近似算法，尚未与原版逐像素校准。
SBS 计算使用 64–512 的固定预览尺寸，完整材质通道尚未接入 3D 视图。
FX-Map、部分参数继承、循环函数及编译 SBSAR 等仍未实现。未知操作会明确报错。
私有 MA017 测试主图目前仅 24/329 个顶层节点能连同上游计算，不能据此认为能完整还原任意 SBS。

## 本机资源

仓库不包含 Adobe 提取图标、原版 QSS、SBS 库、用户材质、包含这些定义的 `.mlsbs` 快照、虚拟环境或本地缓存。
界面使用独立 QSS 和 Qt 标准图标回退，因此与本地完整版的图标会有差异。
包装节点需要自行安装 Designer，默认读取 `C:/Program Files/Adobe/Adobe Substance 3D Designer/resources/packages`。
其他位置可以在代码中通过 `SBSProject(path, library=...)` 指定；目前没有库路径设置面板。
`assets/thumbnails` 为本项目程序纹理渲染结果，`shaders` 为实验着色器。

## 检查

不依赖外部材质的模型测试：

```powershell
.venv\Scripts\python -m unittest test_model
```

`test_sbs_*.py` 是集成检查，需要本机 Designer 库，其中部分还需要个人 MA017 测试文件。
`test_sbs_nodes.py` 和 `test_nodes.py` 的提取 DAG 对照还需要本地 `sbs-node-reference.json`，该文件不随仓库分发。
原开发环境 0.12 的 145 项检查通过；这不等于在新环境中执行了全部测试，也不是原引擎精度认证。

没有为项目指定开源许可证；第三方依赖各自适用其许可证。
