# 图书借阅原型样例

本目录保存成员提供的 `experiment.bookBorrowSystem` 样例副本，用于代码知识问询的可行性实验。原文件位于成员本地 Java 练习工程；本次按成员要求提交副本，未指定或新增独立开源许可证。

副本仅将初始姓名改为“演示读者”、初始 ID 改为 `DEMO-READER-001`，统一 UTF-8 无 BOM 与 LF 换行；不改变业务逻辑或行数。原始文件不修改。保留日期计算、输入校验等原有局限，供问答准确性评测。

源码：`src/experiment/bookBorrowSystem.java`。快照登记见本目录 `snapshot.json`（在源码首次提交后登记完整提交号）；原型方案见 [测试记录](../../docs/图书借阅原型测试记录.md)。

## 复现编译和启动检查

安装 JDK 17 或更高版本并将 `java`、`javac` 加入 PATH；安装 Python 3。于仓库根目录执行：

```powershell
python scripts/prototype/check_sample.py
```

脚本使用 `javac -encoding UTF-8 --release 17` 编译到临时目录，验证菜单退出及初始图书列表；成功退出码为 0，失败为 1。临时编译产物自动清理，本地 JSON 报告保存在 `reports/book_borrow_sample.json`，不纳入 Git。这个检查不代表借还书全部功能或模型问答通过。

## 手工操作样例

于仓库根目录执行：

```powershell
$sampleBuild = Join-Path $env:TEMP 'book-borrow-demo-build'
New-Item -ItemType Directory -Path $sampleBuild -Force | Out-Null
javac -encoding UTF-8 --release 17 -d $sampleBuild samples/book_borrow/src/experiment/bookBorrowSystem.java
java -Dfile.encoding=UTF-8 -cp $sampleBuild experiment.bookBorrowSystem
```

按菜单操作，输入 `9` 退出。程序使用内存数组，每次启动重新初始化数据。若终端中文显示异常，先检查终端编码；源码和脚本采用 UTF-8。

## 版本和索引规则

`snapshot.json` 中的 repository_id 固定用于该样例所属仓库，不随成员电脑路径变化；源码使用仓库根目录相对路径。入库时以登记的完整 commit_sha 读取文件，而非直接读取可能被修改的工作区。snapshot_id 按现有 Schema 由 repository_id 和 commit_sha 生成。

样例修改后须重新验证、提交并登记新快照，再建立新版本索引；图谱、向量及引用不可混用两个快照。本目录不是 Java 解析器或问询平台的实现。
