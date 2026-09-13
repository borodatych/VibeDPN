import { Button } from '@/components/ui/button'

export const CodeExample = ({ example, github, branch }: { example: string; github: string; branch: string }) => {
  const examplePath = `/tree/${branch}/${example}`
  const githubDevUrl = `${github.replace('https://github.com', 'https://github.dev')}${examplePath}`
  const githubSourceUrl = `${github}${examplePath}`
  const codesandboxUrl = `https://codesandbox.io/p/devbox/${github.replace('https://github.com', 'github')}${examplePath}`
  return (
    <div className="flex flex-row gap-buttons-gap-lg">
      <Button size="2xl" variant="outline" href={codesandboxUrl} newTab>
        Codesandbox
      </Button>
      <Button size="2xl" variant="outline" href={githubDevUrl} newTab>
        GitHub Dev
      </Button>
      <Button size="2xl" variant="outline" href={githubSourceUrl} newTab>
        GitHub Source
      </Button>
    </div>
  )
}
