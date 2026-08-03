#!/usr/bin/env python3
"""
CortexLLM Loop Guard System
Detects and prevents repetitive failure loops.
Tracks attempts, detects patterns, and forces strategy changes.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta

class LoopGuard:
    """Prevents repetitive failure loops and forces strategy changes"""
    
    def __init__(self, max_attempts: int = 3, window_minutes: int = 10):
        self.max_attempts = max_attempts
        self.window = timedelta(minutes=window_minutes)
        self.state_file = Path.home() / '.config/cortexllm/loop_guard_state.json'
        self.attempts = self._load_state()
    
    def _load_state(self) -> Dict:
        """Load attempt history from disk"""
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text())
                # Convert timestamp strings back to floats
                for key, entries in data.items():
                    for entry in entries:
                        if 'timestamp' in entry:
                            entry['timestamp'] = float(entry['timestamp'])
                return data
        except:
            pass
        return {}
    
    def _save_state(self):
        """Save attempt history to disk"""
        try:
            # Convert timestamps to strings for JSON
            serializable = {}
            for key, entries in self.attempts.items():
                serializable[key] = []
                for entry in entries:
                    entry_copy = entry.copy()
                    if 'timestamp' in entry_copy:
                        entry_copy['timestamp'] = str(entry_copy['timestamp'])
                    serializable[key].append(entry_copy)
            
            self.state_file.write_text(json.dumps(serializable, indent=2))
        except Exception as e:
            print(f"LoopGuard: Failed to save state: {e}")
    
    def _cleanup_old_entries(self, task_key: str):
        """Remove entries outside the time window"""
        if task_key not in self.attempts:
            return
        
        cutoff = time.time() - self.window.total_seconds()
        self.attempts[task_key] = [
            e for e in self.attempts[task_key]
            if e.get('timestamp', 0) > cutoff
        ]
    
    def record_attempt(self, task_key: str, approach: str, success: bool, error: str = None):
        """
        Record an attempt at a task
        
        task_key: Unique identifier for the task (e.g., "install_cortexllm")
        approach: Description of the approach tried (e.g., "systemd_service_v1")
        success: Whether the attempt succeeded
        error: Error message if failed
        """
        if task_key not in self.attempts:
            self.attempts[task_key] = []
        
        self._cleanup_old_entries(task_key)
        
        attempt = {
            'timestamp': time.time(),
            'approach': approach,
            'success': success,
            'error': error[:200] if error else None
        }
        
        self.attempts[task_key].append(attempt)
        self._save_state()
    
    def check_loop(self, task_key: str, approach: str) -> Dict:
        """
        Check if we're in a failure loop
        
        Returns: {
            'in_loop': bool,
            'attempt_count': int,
            'failure_count': int,
            'recommendation': str
        }
        """
        if task_key not in self.attempts:
            return {'in_loop': False, 'attempt_count': 0, 'failure_count': 0}
        
        self._cleanup_old_entries(task_key)
        entries = self.attempts[task_key]
        
        attempt_count = len(entries)
        failure_count = sum(1 for e in entries if not e['success'])
        
        # Check for loop conditions
        in_loop = False
        recommendation = ""
        
        # Condition 1: Same approach failed multiple times
        same_approach_failures = [
            e for e in entries
            if e['approach'] == approach and not e['success']
        ]
        
        if len(same_approach_failures) >= 2:
            in_loop = True
            recommendation = f"STOP: Same approach '{approach}' has failed {len(same_approach_failures)} times. Try a fundamentally different approach."
        
        # Condition 2: Too many total failures
        elif failure_count >= self.max_attempts:
            in_loop = True
            recommendation = f"STOP: {failure_count} failures in {self.window.minutes} minutes. Step back and diagnose root cause before continuing."
        
        # Condition 3: Rapid retries (more than 3 attempts in 2 minutes)
        recent = [e for e in entries if time.time() - e['timestamp'] < 120]
        if len(recent) >= 3:
            in_loop = True
            recommendation = "STOP: Too many rapid attempts. Take a break and reassess."
        
        return {
            'in_loop': in_loop,
            'attempt_count': attempt_count,
            'failure_count': failure_count,
            'recommendation': recommendation,
            'recent_approaches': list(set(e['approach'] for e in entries))
        }
    
    def get_alternative_approaches(self, task_key: str, current_approach: str) -> List[str]:
        """Get list of approaches that haven't been tried yet (for common tasks)"""
        known_approaches = {
            'service_install': [
                'systemd_user_service',
                'systemd_system_service',
                'supervisord',
                'cron_with_watchdog',
                'docker_container'
            ],
            'config_sync': [
                'direct_copy',
                'symlink',
                'rsync',
                'git_submodule',
                'config_management_tool'
            ],
            'memory_persistence': [
                'json_files',
                'sqlite_database',
                'redis_cache',
                'file_locking'
            ]
        }
        
        tried = set(e['approach'] for e in self.attempts.get(task_key, []))
        alternatives = known_approaches.get(task_key, [])
        
        return [a for a in alternatives if a not in tried]
    
    def reset_task(self, task_key: str):
        """Reset attempt history for a task"""
        if task_key in self.attempts:
            del self.attempts[task_key]
            self._save_state()
    
    def get_status(self, task_key: str = None) -> Dict:
        """Get status of all tracked tasks or a specific task"""
        if task_key:
            return {
                task_key: self.check_loop(task_key, 'current')
            }
        
        status = {}
        for key in self.attempts:
            status[key] = self.check_loop(key, 'unknown')
        
        return status


# Global instance
guard = LoopGuard()


def record(task: str, approach: str, success: bool, error: str = None):
    """Convenience function to record an attempt"""
    guard.record_attempt(task, approach, success, error)


def check(task: str, approach: str) -> Dict:
    """Convenience function to check for loops"""
    return guard.check_loop(task, approach)


if __name__ == '__main__':
    print("Testing Loop Guard System\n")
    
    # Simulate some attempts
    guard.record_attempt('test_task', 'approach_a', False, 'Error 1')
    guard.record_attempt('test_task', 'approach_a', False, 'Error 2')
    guard.record_attempt('test_task', 'approach_b', True, None)
    
    # Check status
    status = guard.check_loop('test_task', 'approach_a')
    print(f"Test task status: {json.dumps(status, indent=2)}")
    
    # Get alternatives
    alts = guard.get_alternative_approaches('service_install', 'systemd_user_service')
    print(f"\nAlternative approaches for service_install: {alts}")
