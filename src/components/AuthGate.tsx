'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, ShieldAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { getCurrentUser, type CurrentUser } from '@/lib/auth';

interface AuthGateProps {
  children: React.ReactNode;
  adminOnly?: boolean;
  onUser?: (user: CurrentUser) => void;
}

export function AuthGate({ children, adminOnly = false, onUser }: AuthGateProps) {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    getCurrentUser()
      .then((currentUser) => {
        if (cancelled) return;
        if (!currentUser) {
          router.replace('/login');
          return;
        }
        setUser(currentUser);
        onUser?.(currentUser);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [router, onUser]);

  if (isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        正在验证登录状态...
      </div>
    );
  }

  if (!user) {
    return null;
  }

  if (adminOnly && user.role !== 'admin') {
    return (
      <div className="mx-auto max-w-xl py-16">
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5 text-destructive" />
              无权访问
            </CardTitle>
            <CardDescription>该页面仅管理员可访问，请切换管理员账号。</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => router.replace('/event-query')}>返回事件数据查询</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return <>{children}</>;
}
