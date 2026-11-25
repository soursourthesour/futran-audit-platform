import { useLocation } from 'react-router-dom';
import { ButtonLink } from '@/components/ui';
import { AuthLayout } from './AuthLayout';

/* Any address no route matches (BUG-10). It used to send people home with no message. */
export function NotFound() {
  const { pathname } = useLocation();
  return (
    <AuthLayout>
      <div className="panel">
        <h1>Page not found</h1>
        <p>There is no page at <code>{pathname}</code>. Check the address, or go to your home page.</p>
        <ButtonLink to="/" variant="primary">Go to the home page</ButtonLink>
      </div>
    </AuthLayout>
  );
}
