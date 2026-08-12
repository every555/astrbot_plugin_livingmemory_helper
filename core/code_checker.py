"""
代码检查模块 - 帮老婆检查代码有没有问题
"""

import ast
import re
import os
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

@dataclass
class CodeIssue:
    """代码问题"""
    line: int
    column: int
    severity: str  # error, warning, info
    category: str  # syntax, import, api, style, bug
    message: str
    suggestion: str = ""

class CodeChecker:
    """代码检查器"""
    
    # AstrBot API常见的正确用法
    ASTRBOT_API_PATTERNS = {
        # ── 装饰器 / 过滤器 ──
        'filter.command': '应使用 @filter.command("命令名") 装饰器注册指令',
        'filter.regex': '应使用 @filter.regex(r"正则表达式") 装饰器注册正则匹配',
        'filter.on_llm_request': '应使用 @filter.on_llm_request() 装饰器拦截 LLM 请求前',
        'filter.on_llm_response': '应使用 @filter.on_llm_response() 装饰器拦截 LLM 响应后',
        'filter.event_message_type': '应使用 @filter.event_message_type(EventMessageType) 过滤消息类型',
        'filter.platform_adapter_type': '应使用 @filter.platform_adapter_type(PlatformAdapterType) 过滤平台',
        'filter.permission_type': '应使用 @filter.permission_type(...) 过滤权限',
        # ── 消息回复 ──
        'event.plain_result': '应使用 yield event.plain_result("文本") 回复纯文本',
        'event.image_result': '应使用 yield event.image_result(url_or_path) 回复图片',
        'event.make_result': '应使用 event.make_result() 创建消息结果，再设置 message_chain 发送复杂消息',
        # ── 消息组件 (astrbot.api.message_components) ──
        'Comp.Plain': 'Plain("文本") — 纯文本消息组件',
        'Comp.Image': 'Image.fromFileSystem(path) 或 Image.fromURL(url) — 图片组件',
        'Comp.At': 'At(qq=123456) — @某人组件',
        'Comp.Reply': 'Reply(id=msg_id) — 回复引用组件',
        # ── Agent Tools (LLM工具注册) ──
        'context.add_llm_tools': '应使用 self.context.add_llm_tools() 注册 LLM 可调用工具',
        'llm_tool': '应使用 @llm_tool(name="工具名") 装饰器注册 LLM 工具函数',
        # ── 配置 / 上下文 ──
        'AstrBotConfig': '插件配置类，通过 @filter.command 等注入',
        'event.unified_msg_origin': '消息来源标识，可用于主动推送消息 (self.context.send_message)',
        # ── 日志 ──
        'logger.info': 'logger.info("信息") — 普通日志',
        'logger.warning': 'logger.warning("警告") — 警告日志',
        'logger.error': 'logger.error("错误", exc_info=True) — 错误日志+堆栈',
        'logger.debug': 'logger.debug("调试") — 调试日志',
        # ── 常用 import ──
        'astrbot.api.event': 'from astrbot.api.event import filter, AstrMessageEvent',
        'astrbot.api.message_components': 'import astrbot.api.message_components as Comp',
        'astrbot.api.all': 'from astrbot.api.all import * — 一键导入所有常用 API',
    }
    
    # 常见的Python语法问题模式
    COMMON_ISSUES = {
        'unterminated_string': '字符串未闭合',
        'missing_colon': '缺少冒号',
        'indentation': '缩进错误',
        'missing_parenthesis': '缺少括号',
        'unused_import': '未使用的import',
        'missing_import': '可能缺少import',
    }
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path
        if db_path:
            self._init_database()
    
    def _init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS code_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                check_time TEXT NOT NULL,
                issues_count INTEGER NOT NULL,
                issues_json TEXT NOT NULL,
                auto_triggered INTEGER DEFAULT 0
            )
        ''')
        conn.commit()
        conn.close()
    
    def check_code(self, code: str, file_path: str = "unknown") -> List[CodeIssue]:
        """检查代码"""
        issues = []
        
        # 1. Python语法检查
        syntax_issues = self._check_syntax(code)
        issues.extend(syntax_issues)
        
        # 2. Import检查
        import_issues = self._check_imports(code)
        issues.extend(import_issues)
        
        # 3. AstrBot API检查
        api_issues = self._check_astrbot_api(code)
        issues.extend(api_issues)
        
        # 4. 代码风格检查
        style_issues = self._check_style(code)
        issues.extend(style_issues)
        
        # 5. 潜在bug检查
        bug_issues = self._check_potential_bugs(code)
        issues.extend(bug_issues)
        
        # 保存检查结果
        if self.db_path:
            self._save_check_result(file_path, issues)
        
        return issues
    
    def _check_syntax(self, code: str) -> List[CodeIssue]:
        """检查Python语法"""
        issues = []
        
        try:
            ast.parse(code)
        except SyntaxError as e:
            issues.append(CodeIssue(
                line=e.lineno or 0,
                column=e.offset or 0,
                severity="error",
                category="syntax",
                message=f"语法错误: {e.msg}",
                suggestion="请检查该行的语法"
            ))
        
        # 检查常见的语法问题模式
        lines = code.split('\n')
        
        for i, line in enumerate(lines, 1):
            # 检查未闭合的字符串
            if line.count('"') % 2 != 0 or line.count("'") % 2 != 0:
                # 可能是多行字符串的开始，检查后续行
                if '"""' not in line and "'''" not in line:
                    issues.append(CodeIssue(
                        line=i,
                        column=0,
                        severity="error",
                        category="syntax",
                        message="字符串可能未闭合",
                        suggestion="检查引号是否匹配"
                    ))
            
            # 检查缺少冒号
            for keyword in ['if', 'elif', 'else', 'for', 'while', 'def', 'class', 'try', 'except', 'finally', 'with']:
                stripped = line.strip()
                if stripped.startswith(keyword) and not stripped.endswith(':'):
                    # 检查是否是多行语句
                    if not stripped.endswith('\\') and not stripped.endswith(','):
                        issues.append(CodeIssue(
                            line=i,
                            column=len(line) - len(line.lstrip()),
                            severity="warning",
                            category="syntax",
                            message=f"语句 '{keyword}' 可能缺少冒号",
                            suggestion="在行末添加冒号 ':'"
                        ))
        
        return issues
    
    def _check_imports(self, code: str) -> List[CodeIssue]:
        """检查import"""
        issues = []
        
        # 提取所有import
        imports = set()
        used_names = set()
        
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # 检查 import xxx
            match = re.match(r'^import\s+(\w+)', stripped)
            if match:
                imports.add(match.group(1))
                continue
            
            # 检查 from xxx import yyy
            match = re.match(r'^from\s+\w+\s+import\s+(.+)', stripped)
            if match:
                names = match.group(1).split(',')
                for name in names:
                    name = name.strip().split(' as ')[0]
                    if name != '*':
                        imports.add(name)
                continue
        
        # 检查未使用的import（简单检测）
        # 这里只做简单的文本匹配，不完全准确
        for imp in imports:
            # 排除常见的需要保留的import
            if imp in ['os', 'sys', 'json', 're', 'datetime', 'typing', 'Optional', 'List', 'Dict']:
                continue
            # 检查是否在代码中使用（除了import行）
            if code.count(imp) == 1:  # 只在import行出现
                issues.append(CodeIssue(
                    line=0,
                    column=0,
                    severity="warning",
                    category="import",
                    message=f"import '{imp}' 可能未使用",
                    suggestion="如果确实不需要，可以删除这个import"
                ))
        
        return issues
    
    def _check_astrbot_api(self, code: str) -> List[CodeIssue]:
        """检查AstrBot API使用"""
        issues = []
        
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # ── event.plain_result 需要 yield ──
            if 'event.plain_result' in stripped and 'yield' not in stripped:
                issues.append(CodeIssue(
                    line=i, column=0, severity="error", category="api",
                    message="event.plain_result 需要使用 yield",
                    suggestion="改为 yield event.plain_result(...)"
                ))
            
            # ── event.image_result 需要 yield ──
            if 'event.image_result' in stripped and 'yield' not in stripped:
                issues.append(CodeIssue(
                    line=i, column=0, severity="error", category="api",
                    message="event.image_result 需要使用 yield",
                    suggestion="改为 yield event.image_result(url_or_path)"
                ))
            
            # ── await 只能在 async 函数中使用 ──
            if 'await' in stripped:
                preceding = '\n'.join(lines[max(0, i-30):i])
                if 'async def' not in preceding:
                    issues.append(CodeIssue(
                        line=i, column=0, severity="warning", category="api",
                        message="await 只能在 async 函数中使用",
                        suggestion="确保函数使用 async def 定义"
                    ))
            
            # ── 字符串换行检查 ──
            if stripped.startswith('"') and stripped.endswith('"'):
                if '\n' in stripped[1:-1]:
                    issues.append(CodeIssue(
                        line=i, column=0, severity="error", category="syntax",
                        message="字符串中不能直接换行",
                        suggestion='使用 \\n 或三引号 """ """'
                    ))
            
            # ── @filter.command 需要带括号调用 ──
            if stripped.startswith('@filter.command') and stripped == '@filter.command':
                issues.append(CodeIssue(
                    line=i, column=0, severity="error", category="api",
                    message="@filter.command 缺少括号和参数",
                    suggestion='改为 @filter.command("命令名")'
                ))
            
            # ── @filter 装饰器需要 () 调用 ──
            for deco in ['on_llm_request', 'on_llm_response', 'regex']:
                if f'@filter.{deco}' in stripped and f'@filter.{deco}()' not in stripped:
                    issues.append(CodeIssue(
                        line=i, column=0, severity="error", category="api",
                        message=f"@filter.{deco} 需要括号调用",
                        suggestion=f"改为 @filter.{deco}()"
                    ))
                    break
            
            # ── @llm_tool 注册检查 ──
            if stripped.startswith('@llm_tool') and 'async def' not in stripped:
                if i < len(lines) and 'async def' not in lines[i]:
                    issues.append(CodeIssue(
                        line=i, column=0, severity="error", category="api",
                        message="@llm_tool 必须装饰在 async def 函数上",
                        suggestion="改为装饰 async def 函数"
                    ))
        
        return issues
    
    def _check_style(self, code: str) -> List[CodeIssue]:
        """检查代码风格"""
        issues = []
        
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            # 检查行末空格
            if line != line.rstrip():
                issues.append(CodeIssue(
                    line=i,
                    column=len(line),
                    severity="info",
                    category="style",
                    message="行末有多余空格",
                    suggestion="删除行末空格"
                ))
            
            # 检查过长的行
            if len(line) > 120:
                issues.append(CodeIssue(
                    line=i,
                    column=120,
                    severity="info",
                    category="style",
                    message="行长度超过120字符",
                    suggestion="考虑拆分长行"
                ))
            
            # 检查缩进（4空格为一个缩进级别）
            stripped = line.lstrip()
            if stripped and not line.startswith('\t'):
                indent = len(line) - len(stripped)
                if indent % 4 != 0:
                    issues.append(CodeIssue(
                        line=i,
                        column=0,
                        severity="info",
                        category="style",
                        message="缩进不是4的倍数",
                        suggestion="使用4个空格作为缩进"
                    ))
        
        return issues
    
    def _check_potential_bugs(self, code: str) -> List[CodeIssue]:
        """检查潜在bug"""
        issues = []
        
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            
            # 检查可能的None比较
            if '==' in stripped and 'None' in stripped:
                if 'is None' not in stripped and 'is not None' not in stripped:
                    issues.append(CodeIssue(
                        line=i,
                        column=0,
                        severity="warning",
                        category="bug",
                        message="比较None应使用 'is None' 或 'is not None'",
                        suggestion="将 == None 改为 is None"
                    ))
            
            # 检查可能的可变默认参数
            match = re.search(r'def\s+\w+\s*\([^)]*=\s*(\[\]|\{\})', stripped)
            if match:
                issues.append(CodeIssue(
                    line=i,
                    column=0,
                    severity="warning",
                    category="bug",
                    message="函数默认参数使用了可变对象",
                    suggestion="使用 None 作为默认值，在函数内初始化"
                ))
            
            # 检查可能的裸except
            if stripped == 'except:' or stripped.startswith('except:'):
                issues.append(CodeIssue(
                    line=i,
                    column=0,
                    severity="warning",
                    category="bug",
                    message="裸except会捕获所有异常",
                    suggestion="指定具体异常类型，如 except Exception:"
                ))
        
        return issues
    
    def _save_check_result(self, file_path: str, issues: List[CodeIssue]):
        """保存检查结果"""
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            INSERT INTO code_checks (file_path, check_time, issues_count, issues_json, auto_triggered)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            file_path,
            datetime.now().isoformat(),
            len(issues),
            json.dumps([{
                'line': issue.line,
                'column': issue.column,
                'severity': issue.severity,
                'category': issue.category,
                'message': issue.message,
                'suggestion': issue.suggestion
            } for issue in issues], ensure_ascii=False),
            0
        ))
        conn.commit()
        conn.close()
    
    def format_issues(self, issues: List[CodeIssue], file_path: str = None) -> str:
        """格式化问题输出"""
        if not issues:
            return "✅ 代码检查通过，没有发现问题！"
        
        lines = []
        if file_path:
            lines.append(f"📋 代码检查报告 - {file_path}")
        else:
            lines.append("📋 代码检查报告")
        lines.append("=" * 40)
        
        # 按严重程度分组
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        infos = [i for i in issues if i.severity == "info"]
        
        if errors:
            lines.append(f"\n❌ 错误 ({len(errors)})")
            for issue in errors:
                lines.append(f"  [{issue.category}] 第{issue.line}行: {issue.message}")
                if issue.suggestion:
                    lines.append(f"    💡 建议: {issue.suggestion}")
        
        if warnings:
            lines.append(f"\n⚠️ 警告 ({len(warnings)})")
            for issue in warnings:
                lines.append(f"  [{issue.category}] 第{issue.line}行: {issue.message}")
                if issue.suggestion:
                    lines.append(f"    💡 建议: {issue.suggestion}")
        
        if infos:
            lines.append(f"\nℹ️ 提示 ({len(infos)})")
            for issue in infos[:5]:  # 只显示前5个提示
                lines.append(f"  [{issue.category}] 第{issue.line}行: {issue.message}")
            if len(infos) > 5:
                lines.append(f"  ... 还有 {len(infos) - 5} 个提示")
        
        lines.append(f"\n📊 统计: {len(errors)} 错误, {len(warnings)} 警告, {len(infos)} 提示")
        
        return "\n".join(lines)
    
    def check_file(self, file_path: str) -> List[CodeIssue]:
        """检查文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            return self.check_code(code, file_path)
        except FileNotFoundError:
            return [CodeIssue(
                line=0,
                column=0,
                severity="error",
                category="syntax",
                message=f"文件不存在: {file_path}",
                suggestion="检查文件路径是否正确"
            )]
        except Exception as e:
            return [CodeIssue(
                line=0,
                column=0,
                severity="error",
                category="syntax",
                message=f"读取文件失败: {str(e)}",
                suggestion="检查文件权限"
            )]
    
    def get_check_history(self, limit: int = 10) -> List[Dict]:
        """获取检查历史"""
        if not self.db_path:
            return []
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute('''
            SELECT * FROM code_checks 
            ORDER BY check_time DESC 
            LIMIT ?
        ''', (limit,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'file_path': row['file_path'],
                'check_time': row['check_time'],
                'issues_count': row['issues_count'],
                'auto_triggered': bool(row['auto_triggered'])
            })
        
        conn.close()
        return results


# ==================== 自动检查钩子 ====================

class AutoCodeChecker:
    """自动代码检查器"""
    
    def __init__(self, checker: CodeChecker, watch_dirs: List[str] = None):
        self.checker = checker
        self.watch_dirs = watch_dirs or []
        self._last_check = {}
    
    def should_check(self, file_path: str) -> bool:
        """判断是否应该检查该文件"""
        # 只检查Python文件
        if not file_path.endswith('.py'):
            return False
        
        # 检查是否在监视目录中
        for watch_dir in self.watch_dirs:
            if file_path.startswith(watch_dir):
                return True
        
        return False
    
    def on_file_write(self, file_path: str, content: str = None):
        """文件写入后的回调"""
        if not self.should_check(file_path):
            return None
        
        # 检查是否刚刚检查过（避免重复）
        now = datetime.now().timestamp()
        if file_path in self._last_check:
            if now - self._last_check[file_path] < 5:  # 5秒内不重复检查
                return None
        
        self._last_check[file_path] = now
        
        # 执行检查
        if content:
            issues = self.checker.check_code(content, file_path)
        else:
            issues = self.checker.check_file(file_path)
        
        return issues
