import { ButtonLink, EmptyState, Page } from '../components/ui.jsx'

export default function NotFoundPage() {
  return (
    <Page>
      <EmptyState icon="alert" title="Page not found" action={<ButtonLink variant="accent" to="/">Go home</ButtonLink>}>
        That address does not match anything in AgentEscrow.
      </EmptyState>
    </Page>
  )
}
