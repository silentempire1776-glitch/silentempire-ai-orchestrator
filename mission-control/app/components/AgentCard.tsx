export default function AgentCard({ name, role, tags }: any) {
  return (

    <div className="glass p-5 hover-lift">

      <h3 className="text-lg font-bold">{name}</h3>
      <p className="text-gray-400 text-sm mb-3">{role}</p>

      <div className="flex gap-2 flex-wrap">

        {tags.map((tag: string) => (
          <span
            key={tag}
            className="text-xs bg-purple-600/20 px-2 py-1 rounded"
          >
            {tag}
          </span>
        ))}

      </div>

    </div>

  )
}
