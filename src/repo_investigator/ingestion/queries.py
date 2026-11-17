from gql import gql

COMMITS_QUERY = gql("""
query Commits(
  $owner: String!, $name: String!, $since: GitTimestamp!, $until: GitTimestamp, $after: String
) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(since: $since, until: $until, first: 100, after: $after) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              oid
              committedDate
              message
              additions
              deletions
              changedFiles
              author {
                user {
                  login
                }
                email
              }
              parents {
                totalCount
              }
            }
          }
        }
      }
    }
  }
}
""")

ISSUES_QUERY = gql("""
query Issues($owner: String!, $name: String!, $since: DateTime!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(
      first: 50
      after: $after
      orderBy: {field: CREATED_AT, direction: DESC}
      filterBy: {since: $since}
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        title
        state
        createdAt
        closedAt
        author {
          login
        }
        labels(first: 10) {
          nodes {
            name
          }
        }
        comments {
          totalCount
        }
      }
    }
  }
}
""")

PULL_REQUESTS_QUERY = gql("""
query PullRequests($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(
      first: 50
      after: $after
      states: [MERGED, CLOSED]
      orderBy: {field: CREATED_AT, direction: DESC}
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        title
        state
        createdAt
        mergedAt
        closedAt
        author {
          login
        }
        reviews(first: 100) {
          nodes {
            state
            submittedAt
            author {
              login
            }
          }
        }
        comments {
          totalCount
        }
      }
    }
  }
}
""")
