'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, Tags } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { login } from '@/lib/auth';

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setIsLoading(true);
    try {
      await login(username.trim(), password);
      router.replace('/event-query');
      router.refresh();
    } catch (err: any) {
      setError(err?.message || '登录失败');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <Card className="w-full max-w-md border-border/60 bg-card/90">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <Tags className="h-6 w-6 text-primary" />
          </div>
          <CardTitle>登录 TagLens AI</CardTitle>
          <CardDescription>管理员分配事件任务后，审核员可进入事件数据查询页面处理。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="space-y-2">
              <Label htmlFor="username">账号</Label>
              <Input id="username" value={username} onChange={(event) => setUsername(event.target.value)} autoFocus />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            {error ? <div className="text-sm text-destructive">{error}</div> : null}
            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              登录
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
