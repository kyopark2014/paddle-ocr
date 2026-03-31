use aws_config;
use aws_sdk_s3::Client;
use paddle_ocr::{
    engine::{Language, OrientationOptions, create_engine},
    process,
    s3::{download_from_s3, parse_s3_uri},
};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: cli <s3://bucket/key>");
        std::process::exit(1);
    }

    let s3_uri = &args[1];

    let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
    let s3_client = Client::new(&config);

    let (_, key) = parse_s3_uri(s3_uri)?;
    let bytes = download_from_s3(&s3_client, s3_uri).await?;

    let engine = create_engine(Language::Korean, OrientationOptions::default())?;
    let response = process(&engine, &bytes, key, None, None)?;

    let lines: Vec<&str> = response
        .pages
        .iter()
        .flat_map(|p| p.items.iter().map(|i| i.text.as_str()))
        .collect();

    let result = serde_json::json!({ "result": lines.join("\n") });
    println!("{}", serde_json::to_string_pretty(&result)?);

    Ok(())
}
