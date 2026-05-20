# DTC

## 各个文件夹的作用

`sam3`: DTC已修改至兼容sam3，不过在运行时要ignore_missing_imports = true，这个已经写在当前的sam3/pyproject.toml中了，sam3文件夹***请勿使用官网下载版本***，一定会出现不匹配的问题

`scripts`: 是benchmark测试代码，实际并不需要

`ckpt`: 参数文件

## 如何自动安装

我已将安装文件写成自动脚本：

- 推荐使用python 3.12

```bash
bash run.sh install
```
执行命令就可安装

我使用的是`uv`管理项目，如果不是使用uv的话自行更改`run.sh`的内容

记得自己更改`torch`和`torchvision`到合适版本

## 如何运行

推理代码和脚本已集成至`infer*`的一系列文件中，自行参考

