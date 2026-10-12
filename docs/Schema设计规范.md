# 代码知识图谱 Schema 设计规范

版本：0.1.0。编写日期：2026 年 10 月 12 日。适用项目：基于代码知识图谱与大模型的业务逻辑智能问询系统。

本文件将现有协作规范和开题报告中的方向要求转化为具体设计规则。团队已完成核对并确认采用本规范，版本 0.1.0 冻结为解析器、图谱与向量模块的统一接口规范。规范确认不替代解析器、数据库约束、向量索引和样例测试的实现验收。

状态：已核对通过并采用。确认日期：2026 年 10 月 12 日。后续变更按第 10 节的版本与评审流程执行。

## 1 适用范围与规范依据

本规范约束代码解析结果、Neo4j 节点和关系、Milvus 源码关联字段，以及后续检索与引用使用的数据格式。第一版支持 Java 样例项目，核心实体为 Repository、File、Class、Method、Field；Function、API、BusinessConcept、状态机和事务卡片列为后续扩展，不在本版要求中提前实现。

规范依据为[团队协作规范](团队协作规范.md)的 2.2、2.3、5、6.1、6.2 节，[开题报告](开题报告.md)的 4.1—4.5 节，以及仓库[协作约定](../CONTRIBUTING.md)。这里的“必须”表示验收要求，“建议”表示可按实验调整的实现选择。

每条事实必须能回查到同一提交版本的源码或明确的配置。确定性抽取结果、未解析引用和模型推断必须分开保存。解析器、图谱与向量模块必须使用同一份字段定义，不能自行增加同名异义字段。

## 2 命名、类型与空值

| 项目 | 统一规则 |
| --- | --- |
| 数据交换格式 | UTF-8 JSON；对象字段使用英文 snake_case |
| Neo4j 类型名 | Repository、File、Class、Method、Field；均附加公共标签 CodeEntity |
| 关系类型 | 全大写下划线形式，如 CALLS、IMPLEMENTS |
| Milvus collection | 小写英文和下划线；本版建议 code_chunks_v1 |
| 字符串 | 名称和路径区分大小写；不得擅自统一转成小写 |
| 布尔、数字 | 使用 JSON 原生类型，不能以字符串替代 |
| 数组 | 无元素用 []；不得用逗号分隔字符串代替数组 |
| 可选字段 | 缺省时省略；仅明确允许未知值的字段使用 null |
| 未知信息 | 不填造值；必要的未知结果进入诊断或未解析引用记录 |
| 未声明字段 | 核心对象不允许；新增字段须先修订 Schema |

生成数据时不保存密钥、个人信息、机器绝对路径或完整敏感提示词。数据交换对象允许使用嵌套结构，但映射为 Neo4j 属性时必须展开为声明过的标量或标量数组；不可直接把任意嵌套 JSON 当作节点属性。

## 3 标识与代码版本

### 3.1 仓库标识与符号标识

repository_id 使用项目首次登记时分配的 UUID，并存入项目配置或仓库登记表。它不依赖本机目录、远端 URL 或提交号；三个人解析同一个仓库必须使用相同的 repository_id，不得各自生成。

symbol_id 采用以下统一算法：

```text
identity = [repository_id, language, entity_type, canonical_name]
payload = identity 的 JSON 数组编码
          ensure_ascii=false，分隔符为逗号和冒号，不加入空格
symbol_id = "sym_" + SHA256(payload 的 UTF-8 字节) 的小写十六进制摘要
```

language 固定为小写，例如 java；entity_type 与节点类型名完全一致，例如 Method。身份数组中不得加入 commit_sha、行号、摘要或解析器版本。相同符号在不改变其规范名时跨提交保持相同 symbol_id；移动文件导致 File 的规范名改变、类或方法重命名、参数类型变更时会生成新 ID。重命名按删除旧实体、添加新实体处理；保留历史身份的映射属于后续扩展。

| 实体 | canonical_name 规则 | 示例 |
| --- | --- | --- |
| Repository | repository_id | 配置中登记的 UUID |
| File | 规范化的仓库相对路径 | src/main/java/demo/OrderService.java |
| Class | 包名与类型名；嵌套类使用 $ | demo.OrderService、demo.Outer$Inner |
| Method | 所属类规范名#方法名(参数类型列表) | demo.OrderService#cancel(java.lang.String) |
| Field | 所属类规范名#字段名 | demo.Order#status |

方法规范名不包含返回类型、访问修饰符、参数变量名、throws 或行号。构造方法名统一为 <init>；可变参数统一为数组类型，例如 java.lang.String[]；泛型参数在方法身份中采用 Java 擦除后的参数类型。参数类型须经类型解析确认，不能根据简单名称猜测全限定类型。同名类型在不同模块冲突时，本版必须报告冲突并停止对应实体入库；扩展模块命名空间后再处理。

当参数类型或所属类无法确定时，不生成冒充已确认符号的 Method ID。解析结果写入诊断记录，保存原始声明、位置和原因，待语义解析补全后再生成正式实体。本版不承诺处理所有复杂 Java 语法和跨模块类型系统。

### 3.2 快照与唯一键

commit_sha 必须为被解析 Git 提交的完整对象 ID，不使用短提交号；长度遵循该仓库的 Git 对象格式。源码必须来自该提交的快照。对未提交工作区的实验解析应另存，不能标注为某个正式提交的索引。

snapshot_id = repository_id + "@" + commit_sha。entity_key = snapshot_id + ":" + symbol_id。Neo4j 以 entity_key 建立唯一约束；symbol_id 表示逻辑符号身份，entity_key 表示某个提交中的实体。多个快照允许包含相同 symbol_id，查询必须过滤 snapshot_id，不能混用不同版本。

## 4 源码定位规则

file_path 使用 / 分隔的仓库相对路径，不以 / 开头，不含 . 或 .. 路径段，不包含盘符。路径应相对真实仓库根目录校验，不能仅通过字符串替换得到。

行号从 1 开始；start_line 和 end_line 均包含边界，且 end_line >= start_line。起点包含直接属于该声明的注解，终点包含声明结束符或闭合花括号；前置注释不计入声明范围，可由后续切片另行扩展。字段多变量声明时，各 Field 可以共享同一声明行范围，但 ID 分别按字段名生成。

解析器需要精确定位时，可另存 source_start_byte 与 source_end_byte：均相对原始文件字节，从 0 开始，起点包含、终点不包含。字节偏移不等于字符列号，不得相互替代。本版不要求保存列号。

每个可引用实体和关系都必须满足：提交存在、文件存在、行号未越界、位置与所声称的声明或调用一致。Repository 没有源码行范围。

## 5 实体数据字典

### 5.1 公共字段

| 字段 | 类型 | 必填范围 | 含义 |
| --- | --- | --- | --- |
| entity_type | string | 全部 | Repository、File、Class、Method、Field 之一 |
| repository_id | string | 全部 | 统一登记的仓库 UUID |
| snapshot_id | string | 全部 | 仓库与提交组合的快照标识 |
| commit_sha | string | 全部 | 完整提交 ID |
| symbol_id | string | 全部 | 按统一算法生成的符号标识 |
| entity_key | string | 全部 | 快照内唯一键 |
| name | string | 全部 | 简短名称，不能为空 |
| canonical_name | string | 全部 | 用于生成 symbol_id 的规范名 |
| language | string | 全部 | 本版固定 java；Repository 表示本次解析语言 |
| extraction_method | string | 全部 | static_ast、semantic_resolution、manual_verified 之一 |
| parser_name | string | 全部 | 抽取工具名称；仓库记录使用生成清单的工具名称 |
| parser_version | string | 全部 | 实际运行工具版本 |
| file_path | string | File、Class、Method、Field | 仓库相对路径 |
| start_line / end_line | integer | File、Class、Method、Field | 可核对的源码范围 |

对象中 metadata 的 schema_version 规定整批数据的契约版本，导入器必须检查，不能忽略不兼容版本。

### 5.2 专属字段

| 实体 | 必填专属字段 | 可选字段与限制 |
| --- | --- | --- |
| Repository | 无额外必填字段 | source_url 可记录脱敏远端地址，不能带凭证 |
| File | 无额外必填字段 | content_sha256 建议保存原始文件摘要；空文件不生成可引用的 File 实体，写入清单诊断 |
| Class | kind、package_name | kind 为 class、interface、enum、annotation、record；默认包 package_name 为 ""；modifiers 为去重字符串数组 |
| Method | declaring_type_id、parameter_types、return_type、is_constructor | parameter_types 为规范类型数组；构造方法 return_type 为 null，其他方法为规范类型；modifiers 为数组 |
| Field | declaring_type_id、field_type | field_type 为已确认的规范类型；modifiers 为数组 |

declaring_type_id 指向同一 snapshot_id 下的 Class.symbol_id。名称不得包含未经说明的临时缩写。未声明业务摘要、模型置信度等字段不直接写入本版确定性实体；后续业务语义数据应形成独立契约。

## 6 关系数据字典

### 6.1 允许的关系与方向

| 类型 | 起点 → 终点 | 含义与约束 |
| --- | --- | --- |
| CONTAINS | Repository → File | 仓库包含文件；每个 File 在快照内只有一个所属 Repository |
| DECLARES | File → Class；Class → Class/Method/Field | 文件声明顶层类型，类型声明嵌套类型、方法或字段；每个声明实体只保留一个直接声明父级 |
| CALLS | Method → Method | 该方法源码中存在可确认目标的调用；构造调用也使用 CALLS |
| EXTENDS | Class → Class | 子类型指向被继承类型；必须与源码语法及 kind 相容 |
| IMPLEMENTS | Class → Class | 实现类指向接口；目标 kind 必须为 interface |
| IMPORTS | File → Class | 显式单类型导入；本版仅导入可解析到同快照实体的目标 |
| REFERENCES | Method → Field | 方法访问字段；注明读取、写入或读写，不将局部变量当作 Field |

通配符导入、静态导入、外部库符号和未确认调用先保存为未解析引用记录，本版不虚构目标节点。接口继承接口使用 EXTENDS；接口实现不能误存为 IMPLEMENTS。

### 6.2 公共关系字段

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| relationship_type | string | 上表允许的关系类型 |
| relationship_id | string | rel_ 前缀和确定性 SHA256 摘要，算法见下文 |
| relationship_key | string | snapshot_id + ":" + relationship_id |
| repository_id、snapshot_id、commit_sha | string | 与两端实体一致 |
| source_symbol_id、target_symbol_id | string | 两端必须存在于当前快照 |
| extraction_method | string | static_ast、semantic_resolution、manual_verified |
| resolution_status | string | 进入确定性关系集合时只能为 resolved |
| source_file | string | 关系产生的源码路径；CONTAINS 为目标文件路径 |
| source_start_line、source_end_line | integer | 关系发生位置；结构声明关系使用对应声明范围 |
| source_start_byte、source_end_byte | integer | CALLS 和 REFERENCES 必填，用于区分同一行多个发生位置 |
| access_kind | string | REFERENCES 必填，read、write、read_write 之一；其他关系省略 |

relationship_id 使用与 symbol_id 相同的 JSON 编码和 SHA256 方法，输入数组为 [repository_id, relationship_type, source_symbol_id, target_symbol_id, source_file, occurrence]。CALLS/REFERENCES 的 occurrence 为 [source_start_byte, source_end_byte]；其他关系为 null。关系位置变化可产生新关系 ID，增量同步必须删除旧快照对应记录，不假定关系 ID 跨编辑稳定。

resolved 表示抽取工具确认了源码引用目标，不表示运行时一定执行。多态调用若只能确认声明目标，记录该目标；不能把所有可能实现类都标记成确定执行路径。

## 7 未解析引用与推断管理

无法确定目标的调用、导入或字段访问必须进入 unresolved_references，不加入 resolved 关系集合。每条记录包含 source_symbol_id（若可确定）、源码位置、reference_kind、raw_target、reason 和 resolution_status。此类记录的 target_symbol_id 固定为 null，不创建“unknown”共享节点。source_symbol_id 不可确定时也为 null，并保留文件位置。

reason 使用明确枚举：external_symbol、wildcard_import、static_import、dynamic_dispatch、reflection、type_unresolved、unsupported_syntax、parse_error；必要时附带 detail。resolution_status 为 unresolved。模型建议只能进入单独的 inferred 记录，注明模型、参数/提示词版本和证据来源；不得通过改标签绕过确定性关系的校验。

## 8 数据交换结构与样例

一批数据只对应一个 repository_id、commit_sha 和 schema_version。统一顶层结构如下；下面是说明样例，尖括号表示按规则生成的值，不可原样入库。

```json
{
  "metadata": {
    "schema_version": "0.1.0",
    "repository_id": "<登记的UUID>",
    "commit_sha": "<完整提交ID>",
    "snapshot_id": "<repository_id>@<commit_sha>"
  },
  "entities": [],
  "relationships": [],
  "unresolved_references": [],
  "diagnostics": []
}
```

例：demo.OrderService 的 cancel(String orderId) 调用 demo.OrderRepository 的 findById(String orderId)。两者的 Method.canonical_name 分别为 demo.OrderService#cancel(java.lang.String) 和 demo.OrderRepository#findById(java.lang.String)。先建立 Class、Method 与 DECLARES，再由语义解析确认目标，生成从 cancel 到 findById 的 CALLS，并保留调用表达式的行范围与字节范围。仅看到 findById 的文本名称而无法解析所属类型时，应产生 unresolved_references。

正式交付的样例 JSON 必须使用真实样例源码和实际生成的 ID，包含至少两种方法重载、一个字段访问和一个未解析引用；不能只交空数组或占位符。

## 9 Neo4j 与 Milvus 映射

Neo4j 节点使用 CodeEntity 和具体类型双标签，entity_key 唯一且非空；核心字段不允许空字符串。导入前校验必填、类型和引用完整性。为 snapshot_id、symbol_id 及常用规范名查找设置索引；创建命令必须放入版本化 Cypher 脚本，不能只在 Browser 中手工操作。版本与 Neo4j Community 能力不支持的约束，由导入器执行等价校验，不声称数据库已经强制保证。

关系必须连接同一快照的实体。关系重复与 relationship_key 唯一性由导入器做幂等检查；重跑同一数据不得增加重复节点或边。批次失败时停止激活该快照，并记录失败项。

Milvus 的向量记录至少包含 chunk_id、repository_id、snapshot_id、commit_sha、symbol_id、file_path、start_line、end_line、embedding_model 和向量字段。chunk_id 按 [snapshot_id, symbol_id, chunk_index, chunk_content_sha256] 的确定性摘要生成；一个符号可以有多个切片，但不得以 chunk_id 替代 symbol_id。查询同时过滤仓库和快照，再以 symbol_id 关联图节点。

本阶段确定关联字段；Embedding 模型、向量维度、最大字符串长度、索引参数与相似度度量在向量模块实现前另行冻结。更换模型或维度必须创建新版本 collection，不能把不同空间的向量混入一个集合。每次激活新快照前核对图谱、向量及源码可用性；未就绪时沿用上一完整快照或明确返回未就绪状态。

## 10 版本变更与协作流程

schema_version 使用主版本.次版本.修订号。改变 ID 规则、字段含义、类型、必填项、关系方向或删除字段属于破坏性变更，升级主版本；增加兼容的可选能力升级次版本；只修正文档或实现错误且不改变契约升级修订号。实验期也执行此规则，并保存版本变更记录。

开始设计或修改前创建 Issue，列出目标、负责人、输入输出、兼容性、迁移和回退方式。实现从最新 main 创建任务分支；提交设计文档、JSON Schema、样例与必要脚本，通过至少一名非作者评审和现有 CI 后合并。首次设计尚无历史数据时，迁移与回退可写“无既有索引，重建样例”，不能省略该项。

| 成员 | 设计阶段责任 |
| --- | --- |
| 夏高婷、白乐刚 | 实体字段、方法签名与 ID、源码定位和样例解析结果 |
| 周笑彤 | 关系规则、跨模块数据格式及图向量关联字段 |
| 三人共同 | 核对样例与未解析情况，评审冻结版本；由非作者复核、第三人独立验证 |

此表衔接进度计划中的共同负责安排，具体实施者和复核者在每个 Issue 中登记。字段意见分歧应回写 Issue 与本规范，不能让不同模块自行保留不同定义。

## 11 阶段交付与验收标准

| 成果 | 建议路径 | 必须包含的内容 |
| --- | --- | --- |
| 本设计规范 | docs/Schema设计规范.md | 字段、标识、关系、版本及边界 |
| 可执行 JSON Schema | schemas/code_graph.schema.json | 顶层结构、实体/关系类型、必填与枚举校验 |
| Java 样例与预期结果 | samples/java_schema/ | 源码、真实 JSON、预期关系和未解析清单 |
| Neo4j 建库示例 | scripts/schema/neo4j_v1.cypher | 约束、索引及与当前版本一致的执行说明 |
| 设计验收记录 | docs/Schema设计验收记录.md | 版本、样例、检查结果、评审和已知限制 |

上表除本规范外为后续交付要求，路径建议不表示文件已存在。Schema 设计完成至少须通过以下检查：

1. 三人对同一源码和登记配置生成相同 symbol_id；重跑不生成重复实体和关系。
2. 同名重载方法、嵌套类、构造方法、数组/可变参数按规则区分；未确定类型被报告。
3. 所有可引用位置能在指定提交打开；同一行两个调用可以区分。
4. 必填字段缺失、非法枚举、反向关系、悬空目标和跨快照关系被拒绝。
5. 新增、修改、删除、重命名的样例说明清晰；旧位置不会被当作新提交证据。
6. 外部符号、反射等无法确认的引用保留诊断，未被错误计入确定性调用边。
7. 用示例查询说明如何找到某方法、其调用方及关联向量记录；明确实现尚未覆盖的情况。

本阶段先验收契约与样例，解析引擎自动生成能力按后续任务单独验收。评审者在验收记录确认 Schema 版本和输入快照后，才将其作为解析、图谱与向量模块的统一接口。
