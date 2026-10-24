# HN News Bridge

公開済みのHacker News Dashboard SQLiteから、ChatGPTに渡す記事候補を生成する独立ツールです。元のDashboardリポジトリ・Streamlitアプリへは書き込みません。Python 3.10以上、標準ライブラリだけで動きます。GitHub ActionsではPython 3.12を使用します。

## 使い方

`python publish.py` で公開DBの更新を確認し、直近7日から最大40件を生成します。候補の抽出方法は初期版を維持しています。

公開データは次の2ファイルです。日付別のファイルを増やさず上書きし、Gitの履歴には過去版が残ります。

- `public/chatgpt-candidates.md`：ChatGPTに読ませる固定URLの本文。
- `public/candidates.json`：同じ候補の機械処理用データ。ChatGPTに両方渡す必要はありません。

自身のGitHubアカウントでこの独立リポジトリをPublicとして作成し、既定ブランチをmainにします。Actionsの `Update public HN candidates` を手動実行すると初回の動作を確認できます。通常は毎時35分に更新します。06:35 JSTも含みますが、GitHubの実行遅延があり、07:00時点での更新は保証されません。長期間活動のない公開リポジトリでは定期実行が停止する場合があるため、更新日時を確認してください。

ChatGPTに渡すURLは `https://raw.githubusercontent.com/<owner>/<repository>/main/public/chatgpt-candidates.md` です。ブラウザーやChatGPTで実際に読めることを確認してください。未取得・古いデータは最新情報として扱いません。

## データと公開範囲

取得元は `taiyo551/Hacker-News-Dashboard` の `data/hn_dashboard.sqlite` だけです。GitHub APIでそのファイルの最終コミットを調べ、同じ版のDBコピーがあれば再利用します。CIはコミットごとにDBコピーをキャッシュします。キャッシュが削除・失効した場合は再ダウンロードします。元DB側の更新効率とは別の処理です。

公開される記事項目はHN投稿ID・タイトル・原文URL・HNリンク・カテゴリ・日時・スコア・コメント件数・観測増加・キーワード・抽出の手掛かり・公開DB内の短い抜粋です。コメント本文や原文全文は追加取得しません。出典と生成日時も含めます。AIによる5件の選定・原文確認・要約はChatGPT側で行います。

`publish.py` はこれらの決めた項目だけを出力し、個人向けプロンプト、会話、社内資料、環境変数の値は読みません。公開ディレクトリに想定外のファイルがあると停止します。ワークフローのコミット対象も公開2ファイルだけです。生成時にLLMは使わず、記事本文内の命令を実行しません。

このリポジトリに機密情報をコミットしないでください。公開URLは誰でも閲覧できます。将来のコード変更や手作業での追加まで含め、誤公開が絶対に起きないと保証する仕組みではありません。

## 権限と確認

ワークフローでは専用リポジトリ内の短期GITHUB_TOKENを使い、記事2ファイルを更新するジョブにcontents: writeを付与します。PAT・APIキー・追加Secretsは不要です。元Dashboardに対する書き込み権限は与えません。公式Actionsは確認したコミットSHAで固定しています。

`python -m unittest discover -s tests -v` で、抽出・読み取り専用・キャッシュ・破損ダウンロードの扱い・公開範囲・固定名上書きを確認できます。

GitHub Actionsは候補ファイルを更新する処理です。通常のChatGPTの毎朝7時のタスクは別途ChatGPT側で設定します。このコードだけではタスクの作成や通知は行いません。
