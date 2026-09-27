%w(alice bob).each do |u|
  user = Account.find_local(u).user
  user.update_columns(approved: true, confirmed_at: Time.now.utc)
  puts "#{u} approved=#{user.reload.approved} functional=#{user.functional?}"
end
