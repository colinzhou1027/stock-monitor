"""
Git 操作工具
封装 Git 自动提交和推送功能
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from utils.logger import LoggerMixin


class GitUtils(LoggerMixin):
    """Git 操作工具类"""
    
    def __init__(self, repo_dir: str = None):
        """
        初始化
        
        Args:
            repo_dir: Git 仓库目录，默认为项目根目录
        """
        if repo_dir is None:
            # 获取项目根目录
            current_dir = Path(__file__).parent.parent
            repo_dir = current_dir
        
        self.repo_dir = Path(repo_dir)
        self.logger.info(f"GitUtils 初始化，仓库目录: {self.repo_dir}")
    
    def _run_git_command(self, args: list, check: bool = True) -> Tuple[bool, str, str]:
        """
        运行 Git 命令
        
        Args:
            args: Git 命令参数
            check: 是否检查返回码
            
        Returns:
            (是否成功, stdout, stderr)
        """
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            success = result.returncode == 0
            
            if not success and check:
                self.logger.error(f"Git 命令失败: git {' '.join(args)}")
                self.logger.error(f"stderr: {result.stderr}")
            
            return success, result.stdout.strip(), result.stderr.strip()
            
        except subprocess.TimeoutExpired:
            self.logger.error(f"Git 命令超时: git {' '.join(args)}")
            return False, "", "Timeout"
        except Exception as e:
            self.logger.error(f"Git 命令异常: {e}")
            return False, "", str(e)
    
    def is_git_repo(self) -> bool:
        """检查是否是 Git 仓库"""
        success, _, _ = self._run_git_command(["rev-parse", "--git-dir"], check=False)
        return success
    
    def get_current_branch(self) -> Optional[str]:
        """获取当前分支名"""
        success, stdout, _ = self._run_git_command(["branch", "--show-current"])
        return stdout if success else None
    
    def has_changes(self, path: str = "docs/") -> bool:
        """
        检查指定路径是否有未提交的更改
        
        Args:
            path: 检查的路径
            
        Returns:
            是否有更改
        """
        # 先 add 一下以检测新文件
        self._run_git_command(["add", path], check=False)
        
        # 检查 staged 和 unstaged 的更改
        success, stdout, _ = self._run_git_command(
            ["status", "--porcelain", path],
            check=False
        )
        
        return bool(stdout.strip())
    
    def add_files(self, path: str = "docs/") -> bool:
        """
        添加文件到暂存区
        
        Args:
            path: 要添加的路径
            
        Returns:
            是否成功
        """
        success, _, _ = self._run_git_command(["add", path])
        if success:
            self.logger.info(f"已添加 {path} 到暂存区")
        return success
    
    def commit(self, message: str = None) -> bool:
        """
        提交更改
        
        Args:
            message: 提交信息，默认自动生成
            
        Returns:
            是否成功
        """
        if message is None:
            date_str = datetime.now().strftime("%Y-%m-%d")
            message = f"[auto] 更新日报数据 {date_str}"
        
        success, _, stderr = self._run_git_command(["commit", "-m", message])
        
        if success:
            self.logger.info(f"提交成功: {message}")
        elif "nothing to commit" in stderr:
            self.logger.info("没有需要提交的更改")
            return True  # 没有更改也算成功
        
        return success
    
    def push(self, remote: str = "origin", branch: str = None) -> bool:
        """
        推送到远程仓库
        
        Args:
            remote: 远程仓库名
            branch: 分支名，默认当前分支
            
        Returns:
            是否成功
        """
        if branch is None:
            branch = self.get_current_branch()
            if not branch:
                self.logger.error("无法获取当前分支")
                return False
        
        success, _, _ = self._run_git_command(["push", remote, branch])
        
        if success:
            self.logger.info(f"推送成功: {remote}/{branch}")
        
        return success
    
    def commit_and_push(self, path: str = "docs/", message: str = None) -> bool:
        """
        提交并推送更改
        
        Args:
            path: 要提交的路径
            message: 提交信息
            
        Returns:
            是否成功
        """
        # 检查是否是 Git 仓库
        if not self.is_git_repo():
            self.logger.warning("不是 Git 仓库，跳过提交")
            return False
        
        # 检查是否有更改
        if not self.has_changes(path):
            self.logger.info(f"没有需要提交的更改: {path}")
            return True
        
        # 添加文件
        if not self.add_files(path):
            return False
        
        # 提交
        if not self.commit(message):
            return False
        
        # 推送
        # 注意：在 GitHub Actions 中，推送需要正确配置 GITHUB_TOKEN
        push_enabled = os.getenv("GIT_AUTO_PUSH", "true").lower() == "true"
        
        if push_enabled:
            return self.push()
        else:
            self.logger.info("自动推送已禁用 (GIT_AUTO_PUSH=false)")
            return True
    
    def setup_git_config(self, name: str = "Stock Monitor Bot", email: str = "bot@stock-monitor.local") -> bool:
        """
        设置 Git 配置（用于 CI 环境）
        
        Args:
            name: 提交者名称
            email: 提交者邮箱
            
        Returns:
            是否成功
        """
        # 检查是否在 CI 环境
        is_ci = os.getenv("CI", "").lower() == "true" or os.getenv("GITHUB_ACTIONS", "").lower() == "true"
        
        if not is_ci:
            self.logger.info("非 CI 环境，跳过 Git 配置")
            return True
        
        # 设置用户名和邮箱
        success1, _, _ = self._run_git_command(["config", "user.name", name])
        success2, _, _ = self._run_git_command(["config", "user.email", email])
        
        if success1 and success2:
            self.logger.info(f"Git 配置设置成功: {name} <{email}>")
            return True
        
        return False
